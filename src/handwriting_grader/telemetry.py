"""Live progress and Azure usage accounting with explicitly configured pricing."""

import json
import math
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .pricing import RATE_KEYS, valid_rate

DEFAULT_RATES: Dict[str, Dict[str, float]] = {}


def load_pricing_rates(config_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Load verified deployment rates; there are no guessed provider defaults."""
    rates: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in DEFAULT_RATES.items()}

    def load_entries(entries):
        if not isinstance(entries, dict):
            return
        for model, values in entries.items():
            if not isinstance(values, dict):
                continue
            if "short" in values or "long" in values:
                threshold = values.get("long_context_threshold")
                if type(threshold) is not int or threshold <= 0:
                    rates[model] = {}
                    continue
                rates[model] = {"long_context_threshold": threshold}
                for context in ("short", "long"):
                    tier = values.get(context, {})
                    rates[model][context] = {
                        key: float(value) for key, value in tier.items()
                        if key in RATE_KEYS and valid_rate(value)
                    } if isinstance(tier, dict) else {}
            else:
                rates[model] = {
                    key: float(value) for key, value in values.items()
                    if key in RATE_KEYS and valid_rate(value)
                }
    cache_file = Path.home() / ".cache" / "azure-handwriting-grader" / "pricing.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            load_entries(cached)
        except (OSError, ValueError, TypeError):
            pass
    if config_path and Path(config_path).exists():
        try:
            import yaml
            cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
            custom = cfg.get("pricing") if isinstance(cfg, dict) else None
            load_entries(custom)
            sources = cfg.get("pricing_sources", {}) if isinstance(cfg, dict) else {}
            declarations = cfg.get("deployment_models", {}) if isinstance(cfg, dict) else {}
            if isinstance(sources, dict):
                for model, source in sources.items():
                    if not isinstance(source, dict):
                        continue
                    family = declarations.get(model, model) if isinstance(declarations, dict) else None
                    family = family.lower() if isinstance(family, str) else None
                    azure = cfg.get("azure_openai", {})
                    endpoint = azure.get("endpoint") if isinstance(azure, dict) else None
                    if (source.get("model") != family
                            or source.get("azure_endpoint") != endpoint):
                        rates[model] = {}
        except (OSError, ValueError, TypeError):
            pass
    return rates


@dataclass
class CallTrace:
    timestamp: str
    phase: str
    step_label: str
    model: str
    prompt_tokens: int
    candidate_tokens: int
    total_tokens: int
    cached_tokens: int
    thoughts_tokens: int
    images_count: int
    latency_ms: float
    cost_usd: float
    cached_call: bool = False
    cost_known: bool = False
    cache_write_tokens: Optional[int] = None
    cache_write_ttl: Optional[str] = None


class TelemetryTracker:
    def __init__(self, log_dir: Optional[Path] = None, config_path: Optional[Path] = None):
        self.log_dir = Path(log_dir) if log_dir else None
        self.rates_table = load_pricing_rates(config_path)
        self._pricing_config = config_path
        self._pricing_verifier = None
        self.traces: List[CallTrace] = []
        self._lock = threading.Lock()

    @property
    def pricing_verifier(self):
        with self._lock:
            if self._pricing_verifier is None:
                from .pricing import RunPricingVerifier
                self._pricing_verifier = RunPricingVerifier(self._pricing_config, log_dir=self.log_dir)
            return self._pricing_verifier

    def calculate_cost(
        self,
        model: str,
        prompt_tokens: int,
        candidate_tokens: int,
        cached_tokens: int,
        images_count: int = 0,
        cache_write_tokens: Optional[int] = None,
        cache_write_ttl: Optional[str] = None,
    ) -> float:
        cost = self._priced_cost(model, prompt_tokens, candidate_tokens, cached_tokens,
                                 images_count, cache_write_tokens, cache_write_ttl)
        return cost if cost is not None else 0.0

    def _priced_cost(self, model, prompt_tokens, candidate_tokens, cached_tokens,
                     images_count=0, cache_write_tokens=None, cache_write_ttl=None):
        rates = self.rates_table.get(model)
        if not rates:
            return None
        tiered = "short" in rates or "long" in rates
        if tiered:
            threshold = rates.get("long_context_threshold")
            if type(threshold) is not int or threshold <= 0:
                return None
            rates = rates.get("long" if prompt_tokens > threshold else "short", {})
        if not isinstance(rates, dict):
            return None
        if any(type(value) is not int or value < 0
               for value in (prompt_tokens, candidate_tokens, cached_tokens, images_count)):
            return None
        if cached_tokens > prompt_tokens:
            return None
        if cache_write_tokens is None:
            if tiered or "cache_write" in rates or "cache_write_12h" in rates:
                return None
            cache_write_tokens = 0
        if (type(cache_write_tokens) is not int or cache_write_tokens < 0
                or cache_write_tokens + cached_tokens > prompt_tokens):
            return None
        write_key = "cache_write" if cache_write_ttl == "30m" else "cache_write_12h"
        if cache_write_tokens and cache_write_ttl not in ("30m", "12h"):
            return None
        counts = {
            "input": prompt_tokens - cached_tokens - cache_write_tokens,
            "cached": cached_tokens, "output": candidate_tokens,
            write_key: cache_write_tokens, "image": images_count,
        }
        cost = 0.0
        for key, count in counts.items():
            if count:
                if not valid_rate(rates.get(key)):
                    return None
                cost += count * float(rates[key]) / (1 if key == "image" else 1_000_000)
        return round(cost, 6) if math.isfinite(cost) else None

    def record_call(
        self,
        phase: str,
        step_label: str,
        model: str,
        usage_metadata: Any,
        duration_sec: float,
        cached_call: bool = False,
        images_count: int = 0,
    ) -> CallTrace:
        prompt_tokens = getattr(usage_metadata, "prompt_token_count", 0) or 0
        candidate_tokens = getattr(usage_metadata, "candidates_token_count", 0) or 0
        total_tokens = getattr(usage_metadata, "total_token_count", 0) or (prompt_tokens + candidate_tokens)
        cached_tokens = getattr(usage_metadata, "cached_content_token_count", 0) or 0
        thoughts_tokens = getattr(usage_metadata, "thoughts_token_count", 0) or 0
        cache_write_tokens = getattr(usage_metadata, "cache_write_token_count", None)
        cache_write_ttl = getattr(usage_metadata, "cache_write_ttl", None)

        priced_cost = self._priced_cost(model, prompt_tokens, candidate_tokens, cached_tokens,
                                        images_count, cache_write_tokens, cache_write_ttl)
        trace = CallTrace(
            timestamp=datetime.now(timezone.utc).isoformat(),
            phase=phase,
            step_label=step_label,
            model=model,
            prompt_tokens=prompt_tokens,
            candidate_tokens=candidate_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            thoughts_tokens=thoughts_tokens,
            images_count=images_count,
            latency_ms=round(duration_sec * 1000.0, 1),
            cost_usd=priced_cost if priced_cost is not None else 0.0,
            cached_call=cached_call,
            cost_known=bool(usage_metadata is not None and priced_cost is not None),
            cache_write_tokens=cache_write_tokens,
            cache_write_ttl=cache_write_ttl,
        )
        with self._lock:
            self.traces.append(trace)
            if self.log_dir:
                try:
                    self.log_dir.mkdir(parents=True, exist_ok=True)
                    log_file = self.log_dir / "azure_usage.jsonl"
                    with log_file.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(asdict(trace), ensure_ascii=False) + "\n")
                except OSError:
                    pass

        return trace

    def load_existing_log(self, log_path: Path):
        path = Path(log_path)
        if not path.is_file():
            return
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    trace = CallTrace(**data)
                    self.traces.append(trace)
                except Exception:
                    continue

    def get_summary(self) -> Dict[str, Any]:
        total_p = sum(t.prompt_tokens for t in self.traces)
        total_c = sum(t.candidate_tokens for t in self.traces)
        total_cached = sum(t.cached_tokens for t in self.traces)
        total_imgs = sum(t.images_count for t in self.traces)
        total_cost = sum(t.cost_usd for t in self.traces)

        by_phase: Dict[str, Dict[str, Any]] = {}
        by_model: Dict[str, Dict[str, Any]] = {}

        for t in self.traces:
            if t.phase not in by_phase:
                by_phase[t.phase] = {"calls": 0, "total_tokens": 0, "cost_usd": 0.0}
            by_phase[t.phase]["calls"] += 1
            by_phase[t.phase]["total_tokens"] += t.total_tokens
            by_phase[t.phase]["cost_usd"] = round(by_phase[t.phase]["cost_usd"] + t.cost_usd, 5)

            if t.model not in by_model:
                by_model[t.model] = {"calls": 0, "total_tokens": 0, "cost_usd": 0.0}
            by_model[t.model]["calls"] += 1
            by_model[t.model]["total_tokens"] += t.total_tokens
            by_model[t.model]["cost_usd"] = round(by_model[t.model]["cost_usd"] + t.cost_usd, 5)

        for phase, data in by_phase.items():
            if any(not t.cost_known for t in self.traces if t.phase == phase):
                data["cost_usd"] = None
        for model, data in by_model.items():
            if any(not t.cost_known for t in self.traces if t.model == model):
                data["cost_usd"] = None
        unpriced = sum(not t.cost_known for t in self.traces)
        return {
            "total_calls": len(self.traces),
            "total_input_tokens": total_p,
            "total_output_tokens": total_c,
            "total_cached_tokens": total_cached,
            "total_cache_write_tokens": (
                None if any(t.cache_write_tokens is None for t in self.traces)
                else sum(t.cache_write_tokens for t in self.traces)
            ),
            "total_images": total_imgs,
            "total_cost_usd": None if unpriced else round(total_cost, 5),
            "unpriced_calls": unpriced,
            "by_phase": by_phase,
            "by_model": by_model,
        }

    def show_progress(
        self,
        phase: str,
        current: int,
        total: int,
        item_label: str,
        trace: Optional[CallTrace] = None,
        duration_sec: Optional[float] = None,
        extra_note: str = "",
    ) -> str:
        percent = (current / total * 100.0) if total > 0 else 100.0
        header = f"[Azure Progress] [{phase}] ({current}/{total} - {percent:.1f}%)"
        parts = [header, item_label]
        if trace:
            tok_str = f"{trace.prompt_tokens:,} in / {trace.candidate_tokens:,} out"
            if trace.cached_tokens > 0:
                tok_str += f" ({trace.cached_tokens:,} cached)"
            parts.append(tok_str)
            parts.append(f"${trace.cost_usd:.5f}" if trace.cost_known else "cost unpriced")
        if duration_sec is not None:
            parts.append(f"{duration_sec:.1f}s")
        elif trace and trace.latency_ms:
            parts.append(f"{trace.latency_ms / 1000.0:.1f}s")
        if extra_note:
            parts.append(extra_note)

        line = " ── ".join(parts)
        print(line, flush=True)
        return line

    def write_cost_report(self, target_dir: Path) -> Path:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill

        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        report_path = target_dir / "cost_report.xlsx"

        wb = openpyxl.Workbook()

        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

        # 1. Summary Sheet
        ws_sum = wb.active
        ws_sum.title = "Summary"
        ws_sum.append(["Phase", "Calls", "Prompt Tokens", "Candidate Tokens", "Cached Tokens", "Images", "Estimated Cost (USD)"])
        for cell in ws_sum[1]:
            cell.fill = header_fill
            cell.font = header_font

        phases: Dict[str, Dict[str, Any]] = {}
        for t in self.traces:
            if t.phase not in phases:
                phases[t.phase] = {"calls": 0, "p": 0, "c": 0, "cached": 0, "img": 0, "cost": 0.0}
            d = phases[t.phase]
            d["calls"] += 1
            d["p"] += t.prompt_tokens
            d["c"] += t.candidate_tokens
            d["cached"] += t.cached_tokens
            d["img"] += t.images_count
            d["cost"] += t.cost_usd

        for p_name, data in phases.items():
            ws_sum.append([
                p_name,
                data["calls"],
                data["p"],
                data["c"],
                data["cached"],
                data["img"],
                round(data["cost"], 5) if all(t.cost_known for t in self.traces if t.phase == p_name) else "UNPRICED",
            ])

        total_cost = sum(t.cost_usd for t in self.traces)
        total_p = sum(t.prompt_tokens for t in self.traces)
        total_c = sum(t.candidate_tokens for t in self.traces)
        total_cached = sum(t.cached_tokens for t in self.traces)
        total_imgs = sum(t.images_count for t in self.traces)
        known = all(t.cost_known for t in self.traces)
        ws_sum.append(["TOTAL", len(self.traces), total_p, total_c, total_cached, total_imgs, round(total_cost, 5) if known else "UNPRICED"])
        total_row = ws_sum[ws_sum.max_row]
        for cell in total_row:
            cell.font = Font(bold=True)

        # 2. Detailed Journal Sheet
        ws_det = wb.create_sheet("API Audit Log")
        ws_det.append([
            "Timestamp", "Phase", "Step/Item", "Model", "Prompt Tokens",
            "Candidate Tokens", "Cached Tokens", "Thoughts", "Images", "Latency (s)", "Cost (USD)", "Cache Hit",
            "Cache Write Tokens", "Cache Write TTL",
        ])
        for cell in ws_det[1]:
            cell.fill = header_fill
            cell.font = header_font

        for t in self.traces:
            ws_det.append([
                t.timestamp,
                t.phase,
                t.step_label,
                t.model,
                t.prompt_tokens,
                t.candidate_tokens,
                t.cached_tokens,
                t.thoughts_tokens,
                t.images_count,
                round(t.latency_ms / 1000.0, 2),
                round(t.cost_usd, 5) if t.cost_known else "UNPRICED",
                "YES" if t.cached_call else "NO",
                t.cache_write_tokens if t.cache_write_tokens is not None else "UNKNOWN",
                t.cache_write_ttl,
            ])

        for ws in (ws_sum, ws_det):
            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = openpyxl.utils.get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        wb.save(report_path)
        wb.close()

        # Also output JSON summary
        for phase, data in phases.items():
            data["unpriced_calls"] = sum(not t.cost_known for t in self.traces if t.phase == phase)
            if data["unpriced_calls"]:
                data["cost"] = None
        json_summary = {
            "total_calls": len(self.traces),
            "total_prompt_tokens": total_p,
            "total_candidate_tokens": total_c,
            "total_cached_tokens": total_cached,
            "total_cache_write_tokens": self.get_summary()["total_cache_write_tokens"],
            "total_images": total_imgs,
            "total_cost_usd": round(total_cost, 5) if known else None,
            "unpriced_calls": sum(not t.cost_known for t in self.traces),
            "phases": phases,
        }
        with (target_dir / "cost_summary.json").open("w", encoding="utf-8") as f:
            json.dump(json_summary, f, ensure_ascii=False, indent=2)

        return report_path

    def flush_jsonl(self, log_dir: Path) -> Path:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        log_file = log_path / "azure_usage.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            for trace in self.traces:
                f.write(json.dumps(asdict(trace), ensure_ascii=False) + "\n")
        if self._pricing_verifier is not None:
            self._pricing_verifier.flush(log_path)
        return log_file


# Global instance
_ACTIVE_TRACKER: Optional[TelemetryTracker] = None


def set_active_tracker(tracker: Optional[TelemetryTracker]) -> None:
    global _ACTIVE_TRACKER
    _ACTIVE_TRACKER = tracker


def get_thinking_config(model: str, *, is_reasoning: bool = True) -> Optional[Any]:
    """Set reasoning effort only for recognizable reasoning deployment names."""
    from .azure_ai import ReasoningConfig
    if model and model.lower().startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
        return ReasoningConfig(effort="medium" if is_reasoning else "low")
    return None


def get_active_tracker() -> Optional[TelemetryTracker]:
    return _ACTIVE_TRACKER


def get_tracker(log_dir: Optional[Path] = None) -> TelemetryTracker:
    global _ACTIVE_TRACKER
    if _ACTIVE_TRACKER is None:
        _ACTIVE_TRACKER = TelemetryTracker(log_dir=log_dir)
    elif log_dir and _ACTIVE_TRACKER.log_dir is None:
        _ACTIVE_TRACKER.log_dir = Path(log_dir)
        _ACTIVE_TRACKER.log_dir.mkdir(parents=True, exist_ok=True)
    return _ACTIVE_TRACKER
