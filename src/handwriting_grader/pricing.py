"""Microsoft retail snapshots and lazy, run-scoped paid-request verification."""

import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import yaml

from .azure_ai import validate_endpoint
from .discovery import RECOMMENDED_MODELS, validate_model_eligibility


RETAIL_API = "https://prices.azure.com/api/retail/prices"
CONTEXT_SOURCE = (
    "https://learn.microsoft.com/en-us/azure/foundry/foundry-models/"
    "concepts/models-sold-directly-by-azure#short-context-and-long-context"
)
RATE_KEYS = ("input", "cached", "output", "cache_write", "cache_write_12h", "image")
DEPLOYMENT_TYPES = ("global-standard", "data-zone-standard")
MODEL_VERSIONS = {model: version for model, version, _ in RECOMMENDED_MODELS}
EMBEDDING_SKUS = {
    "text-embedding-3-small": "text-embedding-3-small-glbl",
    "text-embedding-3-large": "text-embedding-3-large-glbl",
}
LONG_CONTEXT_THRESHOLD = 272_000
SKU_PATTERN = re.compile(
    r"(?P<version>6\.1|61|6\.2|6)[- ]?(?P<variant>sol|terra|astra|luna) "
    r"(?P<context>shortco|shco|longco|loco) "
    r"(?P<kind>cd inp|cd wr|inp|opt) (?P<mode>std|12hr) (?P<zone>gl|dz)"
)


def valid_rate(value):
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value)) and float(value) >= 0
    except (ValueError, TypeError, OverflowError):
        return False


def _validate_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "prices.azure.com"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.fragment or parsed.path != "/api/retail/prices"):
        raise ValueError("Retail pagination and redirects must stay on the Microsoft prices API")
    return url


class _MicrosoftRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_page(url):
    request = Request(_validate_url(url), headers={"Accept": "application/json"})
    with build_opener(_MicrosoftRedirects()).open(request, timeout=30) as response:
        content = response.read(6 * 1024 * 1024 + 1)
    if len(content) > 6 * 1024 * 1024:
        raise ValueError("Retail pricing response exceeds the response budget")
    return json.loads(content)


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("A meter needs an effective date")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Meter dates must include a timezone")
    return result


def _classify(item, region, deployment_type):
    if (item.get("productName") != "Azure OpenAI GPT6"
            or item.get("serviceName") not in ("Foundry Models", "Cognitive Services")
            or item.get("armRegionName") != region or item.get("currencyCode") != "USD"
            or item.get("type") != "Consumption"):
        return None
    sku = item.get("skuName")
    if not isinstance(sku, str):
        return None
    match = SKU_PATTERN.fullmatch(sku.lower())
    if not match:
        return None
    expected_zone = "gl" if deployment_type == "global-standard" else "dz"
    if match["zone"] != expected_zone:
        return None
    version = "6.1" if match["version"] == "61" else match["version"]
    family = f"gpt-{version}-{match['variant']}"
    if family not in MODEL_VERSIONS:
        return None
    context = "short" if match["context"] in ("shortco", "shco") else "long"
    if match["mode"] == "12hr":
        if match["kind"] != "cd wr":
            return None
        kind = "cache_write_12h"
    else:
        kind = {"inp": "input", "opt": "output", "cd inp": "cached", "cd wr": "cache_write"}[match["kind"]]
    return family, context, kind


def _choose_meter(items, now):
    active = []
    for item in items:
        try:
            effective = _timestamp(item.get("effectiveStartDate"))
        except ValueError:
            return None, "Meter has an invalid effective date"
        if effective <= now:
            active.append((effective, item))
    if not active:
        return None, "No currently effective meter"
    latest = max(effective for effective, _ in active)
    candidates = {json.dumps(item, sort_keys=True): item
                  for effective, item in active if effective == latest}
    if len(candidates) != 1:
        return None, "Multiple current meters match; manual verification required"
    item = next(iter(candidates.values()))
    units = {"1M": 1, "1M Tokens": 1, "1K": 1000, "1K Tokens": 1000}
    unit = item.get("unitOfMeasure")
    if (not isinstance(unit, str) or unit not in units or not valid_rate(item.get("retailPrice"))
            or item.get("tierMinimumUnits") != 0
            or not item.get("meterId") or not item.get("meterName")):
        return None, "Meter has unsupported units, tiering or price metadata"
    price = float(item["retailPrice"]) * units[unit]
    if not valid_rate(price):
        return None, "Meter price cannot be normalized"
    return {
        "rate": price,
        "meter_id": item["meterId"],
        "sku_name": item["skuName"],
        "meter_name": item["meterName"],
        "unit_of_measure": unit,
        "retail_price": item["retailPrice"],
        "effective_start_date": item["effectiveStartDate"],
    }, None


def configured_models(config):
    if not isinstance(config, dict) or not isinstance(config.get("azure_openai"), dict):
        raise ValueError("A private Azure model configuration is required")
    validate_endpoint(config["azure_openai"].get("endpoint"))
    models = config.get("models")
    declarations = config.get("deployment_models", {})
    if not isinstance(models, dict) or not models or not isinstance(declarations, dict):
        raise ValueError("models and deployment_models must be mappings")
    targets = {}
    for agent, deployment in models.items():
        family = declarations.get(deployment, deployment) if isinstance(deployment, str) else None
        validate_model_eligibility(deployment, agent=agent, base_model=family)
        targets[deployment] = family.lower()
    return targets


def lookup_pricing(region, deployment_type, models=None, *, fetch_page=None, now=None):
    if not isinstance(region, str) or not re.fullmatch(r"[a-z][a-z0-9]{1,63}", region):
        raise ValueError("Use the exact Azure ARM region name, such as eastus")
    if deployment_type not in DEPLOYMENT_TYPES:
        raise ValueError("Only synchronous Global Standard or Data Zone Standard pricing is supported")
    models = models if models is not None else {model: model for model in MODEL_VERSIONS}
    now = now or datetime.now(timezone.utc)
    fetch_page = fetch_page or _fetch_page
    query = f"productName eq 'Azure OpenAI GPT6' and armRegionName eq '{region}' and priceType eq 'Consumption'"
    initial_url = f"{RETAIL_API}?{urlencode({'$filter': query})}"
    items, seen = [], set()
    url = initial_url if any(model in MODEL_VERSIONS for model in models.values()) else None
    while url:
        _validate_url(url)
        if url in seen or len(seen) >= 10:
            raise ValueError("Retail pagination is repeated or exceeds ten pages; no snapshot accepted")
        seen.add(url)
        page = fetch_page(url)
        if (not isinstance(page, dict) or not isinstance(page.get("Items"), list)
                or len(page["Items"]) > 1000
                or any(not isinstance(item, dict) for item in page["Items"])):
            raise ValueError("Retail API returned an invalid page")
        items.extend(page["Items"])
        url = page.get("NextPageLink")
        if url is not None and not isinstance(url, str):
            raise ValueError("Retail API returned invalid pagination")

    groups = {}
    for item in items:
        key = _classify(item, region, deployment_type)
        if key:
            groups.setdefault(key, []).append(item)
    embedding_results = {}
    if deployment_type == "global-standard":
        for family in set(models.values()) & EMBEDDING_SKUS.keys():
            sku = EMBEDDING_SKUS[family]
            query = (f"productName eq 'Azure OpenAI' and armRegionName eq '{region}' "
                     f"and skuName eq '{sku}' and priceType eq 'Consumption'")
            embedding_url = f"{RETAIL_API}?{urlencode({'$filter': query})}"
            rows, embedding_seen = [], set()
            while embedding_url:
                _validate_url(embedding_url)
                if embedding_url in embedding_seen or len(embedding_seen) >= 10:
                    raise ValueError("Retail pagination is repeated or exceeds ten pages; no snapshot accepted")
                embedding_seen.add(embedding_url)
                page = fetch_page(embedding_url)
                if (not isinstance(page, dict) or not isinstance(page.get("Items"), list)
                        or len(page["Items"]) > 1000
                        or any(not isinstance(item, dict) for item in page["Items"])):
                    raise ValueError("Retail API returned an invalid page")
                rows.extend(page["Items"])
                embedding_url = page.get("NextPageLink")
                if embedding_url is not None and not isinstance(embedding_url, str):
                    raise ValueError("Retail API returned invalid pagination")
            matching = [item for item in rows
                        if item.get("productName") == "Azure OpenAI"
                        and item.get("serviceName") in ("Foundry Models", "Cognitive Services")
                        and item.get("skuName") == sku and item.get("meterName") == f"{sku} Tokens"
                        and item.get("armRegionName") == region and item.get("currencyCode") == "USD"
                        and item.get("type") == "Consumption"]
            embedding_results[family] = (_choose_meter(matching, now), embedding_seen)
    report = {
        "source": initial_url, "fetched_at": now.isoformat(), "currency": "USD",
        "region": region, "deployment_type": deployment_type,
        "unit": "USD per million tokens", "long_context_threshold": LONG_CONTEXT_THRESHOLD,
        "context_source": CONTEXT_SOURCE, "pages_fetched": len(seen), "deployments": {},
    }
    for deployment, model in models.items():
        entry = {"model": model, "documented_model_version": MODEL_VERSIONS.get(model),
                 "context_threshold_source": f"https://developers.openai.com/api/docs/models/{model}",
                 "status": "UNPRICED", "tiers": {}, "meters": {}, "issues": []}
        report["deployments"][deployment] = entry
        if model in embedding_results:
            (meter, issue), pages = embedding_results[model]
            entry["source"] = next(iter(pages)) if len(pages) == 1 else RETAIL_API
            entry["pages_fetched"] = len(pages)
            entry["input"] = meter["rate"] if meter else None
            entry["meters"] = {"input": meter} if meter else {}
            entry["status"] = "PRICED" if meter else "UNPRICED"
            if issue:
                entry["issues"].append(issue)
            continue
        if model not in MODEL_VERSIONS:
            entry["issues"].append("Automatic lookup does not support this model and deployment type; verify manually")
            continue
        for context in ("short", "long"):
            rates, meters = {}, {}
            for kind in RATE_KEYS[:-1]:
                meter, issue = _choose_meter(groups.get((model, context, kind), []), now)
                rates[kind] = meter["rate"] if meter else None
                if meter:
                    meters[kind] = meter
                else:
                    entry["issues"].append(f"{context}.{kind}: {issue}")
            entry["tiers"][context] = rates
            entry["meters"][context] = meters
        if all(entry["tiers"][context][kind] is not None
               for context in ("short", "long") for kind in ("input", "cached", "output", "cache_write")):
            entry["status"] = "PRICED"
    return report


def priced_config(config, report):
    updated = copy.deepcopy(config)
    updated["pricing_lookup"] = {
        "region": report["region"], "deployment_type": report["deployment_type"],
    }
    pricing = updated.setdefault("pricing", {})
    sources = updated.setdefault("pricing_sources", {})
    if not isinstance(pricing, dict) or not isinstance(sources, dict):
        raise ValueError("pricing and pricing_sources must be mappings")
    for deployment, entry in report["deployments"].items():
        pricing[deployment] = {}
        if entry["tiers"]:
            pricing[deployment] = {
                "long_context_threshold": report["long_context_threshold"],
                **{context: {key: value for key, value in rates.items() if value is not None}
                   for context, rates in entry["tiers"].items()},
            }
        elif entry.get("input") is not None:
            pricing[deployment] = {"input": entry["input"]}
        sources[deployment] = {
            **{key: value for key, value in report.items() if key != "deployments"},
            "azure_endpoint": config["azure_openai"]["endpoint"],
            **entry,
        }
    return updated


def write_priced_config(target, config, report):
    updated = priced_config(config, report)
    write_new_config(target, updated)
    return updated


def write_new_config(target, config):
    target = Path(target)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            yaml.safe_dump(config, file, sort_keys=False)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_and_report(region, deployment_type, model_config=None, write_config=None):
    config = None
    if write_config is not None:
        if model_config is None:
            raise ValueError("--write-config requires --model-config")
        if Path(write_config).exists() or Path(write_config).is_symlink():
            raise FileExistsError("The priced configuration must be a new file")
    if model_config is not None:
        with Path(model_config).open(encoding="utf-8") as file:
            config = yaml.safe_load(file)
        models = configured_models(config)
    else:
        models = None
    report = lookup_pricing(region, deployment_type, models)
    print(f"Microsoft public retail snapshot: {region}, {deployment_type}, USD per 1M tokens")
    print("| Deployment/model | Context | Input | Cached | Output | Cache write 30m | Cache write 12h |")
    print("|---|---|---|---|---|---|---|")
    for deployment, entry in report["deployments"].items():
        if "input" in entry:
            print(f"| {deployment} | embedding | {entry['input'] if entry['input'] is not None else 'UNPRICED'} | - | - | - | - |")
            print(f"Embedding retail source: {entry['source']}")
        for context, rates in entry["tiers"].items():
            values = [str(rates[key]) if rates[key] is not None else "UNPRICED"
                      for key in RATE_KEYS[:-1]]
            print(f"| {deployment} | {context} | {' | '.join(values)} |")
        for issue in entry["issues"]:
            print(f"UNPRICED component for {deployment}: {issue}")
    if report["pages_fetched"]:
        print(f"GPT-6 retail source: {report['source']}")
    print(f"Fetched: {report['fetched_at']}")
    supported = [entry for entry in report["deployments"].values() if entry["tiers"]]
    if (deployment_type == "global-standard" and region != "eastus" and supported
            and all(entry["status"] == "UNPRICED" for entry in supported)):
        print(
            "No effective Global Standard GPT-6 meters were found for this meter profile. "
            "Azure currently publishes these meters under candidate profile 'eastus' in "
            "existing priced configurations. Refresh `fetch-pricing --region eastus "
            "--deployment-type global-standard` and obtain user confirmation of that "
            "retail meter profile; no region was substituted."
        )
    print("Retail estimates only. Verify deployment model/version, billing mode and current prices; this is not your Azure invoice.")
    if report["pages_fetched"]:
        print("Full-request long-context rates apply above 272,000 input tokens.")
    print("No inference, credentials or student data are used.")
    if write_config is not None:
        write_priced_config(write_config, config, report)
        print(f"New priced configuration: {write_config}. Source unchanged; review before using a fresh run.")
    return report


class PriceVerificationError(ValueError):
    """The requested paid operation has no current, reviewed price."""


def pricing_client_options(config_path, log_dir):
    from .telemetry import get_active_tracker

    tracker = get_active_tracker()
    verifier = tracker.pricing_verifier if tracker is not None else None
    if verifier is None or verifier.config_path is None:
        verifier = RunPricingVerifier(config_path, log_dir)
    elif config_path is not None and Path(config_path).expanduser().resolve() != verifier.config_path:
        raise PriceVerificationError("Client and run use different pricing configurations")
    return {"pricing_config": config_path, "pricing_verifier": verifier}


class RunPricingVerifier:
    def __init__(self, config_path=None, log_dir=None, *, fetch_page=None, now=None):
        self.config_path = Path(config_path).expanduser().resolve() if config_path else None
        self.log_dir = Path(log_dir) if log_dir else None
        self._fetch_page = fetch_page
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._signature = None
        self._config = None
        self._reports = {}
        self._verified = {}
        self._errors = set()
        self._blocked_reason = None
        self.checks = []
        self._written = 0

    def _load(self, endpoint, model):
        if self.config_path is None:
            raise PriceVerificationError("A private model configuration is required for price verification")
        content = self.config_path.read_bytes()
        signature = hashlib.sha256(content).hexdigest()
        if self._signature is not None and signature != self._signature:
            raise PriceVerificationError("Model configuration changed; review it and start a new run")
        if self._config is None:
            self._config = yaml.safe_load(content)
            self._signature = signature
        config = self._config
        targets = configured_models(config)
        for deployment, family in config.get("deployment_models", {}).items():
            if isinstance(deployment, str) and isinstance(family, str):
                targets.setdefault(deployment, family.lower())
        if model not in targets:
            raise PriceVerificationError(f"Declare the deployment/model {model!r} in the model configuration")
        declared_endpoint = validate_endpoint(config["azure_openai"]["endpoint"])
        if declared_endpoint.lower() != endpoint.lower():
            raise PriceVerificationError("Azure endpoint differs from the reviewed pricing configuration")
        return config, targets

    @staticmethod
    def _profile(config, model, family, endpoint):
        source = config.get("pricing_sources", {}).get(model, {})
        if source:
            if (source.get("model") != family
                    or source.get("currency") != "USD"
                    or family in MODEL_VERSIONS and source.get("unit") != "USD per million tokens"
                    or validate_endpoint(source.get("azure_endpoint", "")).lower() != endpoint.lower()):
                raise PriceVerificationError("Saved price evidence does not match the deployment family/resource")
        profile = source if source.get("region") and source.get("deployment_type") else config.get("pricing_lookup", {})
        region, mode = profile.get("region"), profile.get("deployment_type")
        if not isinstance(region, str) or not re.fullmatch(r"[a-z][a-z0-9]{1,63}", region):
            raise PriceVerificationError("Set pricing_lookup.region to the exact Azure ARM region")
        if mode not in DEPLOYMENT_TYPES:
            raise PriceVerificationError("Set pricing_lookup.deployment_type to global-standard or data-zone-standard")
        return region, mode

    def _manual_source(self, source, family, endpoint, profile, now, *, unit="USD per million tokens"):
        if (not isinstance(source, dict) or source.get("verification") != "manual"
                or source.get("model") != family or source.get("currency") != "USD"
                or source.get("unit") != unit
                or (source.get("region"), source.get("deployment_type")) != profile
                or validate_endpoint(source.get("azure_endpoint", "")).lower() != endpoint.lower()):
            raise PriceVerificationError("Manual rates need matching model, resource, region, billing mode and USD evidence")
        verified = _timestamp(source.get("verified_at")).astimezone(timezone.utc)
        if verified.date() != now.date() or verified > now:
            raise PriceVerificationError("Manually verify unsupported-model/tool prices today (UTC) before use")
        url = urlsplit(source.get("source", ""))
        if (url.scheme != "https" or url.hostname not in ("azure.microsoft.com", "learn.microsoft.com", "prices.azure.com")
                or url.port not in (None, 443) or url.username or url.password or url.query or url.fragment
                or not any(part in url.path for part in ("pricing", "/retail/prices"))):
            raise PriceVerificationError("Manual price evidence needs an official Microsoft pricing reference URL")

    @staticmethod
    def _rates(row, required, *, tiered=False):
        if not isinstance(row, dict):
            raise PriceVerificationError("Required pricing rates are missing")
        if tiered:
            threshold = row.get("long_context_threshold")
            if type(threshold) is not int or threshold <= 0:
                raise PriceVerificationError("Tiered pricing needs a positive input-token threshold")
            return {"long_context_threshold": threshold,
                    **{tier: RunPricingVerifier._rates(row.get(tier), required) for tier in ("short", "long")}}
        if any(not valid_rate(row.get(key)) for key in required):
            raise PriceVerificationError("Required pricing components are missing or invalid")
        return {key: float(value) for key, value in row.items()
                if key in (*required, "cache_write_12h") and valid_rate(value)}

    def verify(self, endpoint, model, *, kind="text", tools=(), image_size=None):
        with self._lock:
            try:
                if self._blocked_reason is not None:
                    raise PriceVerificationError(self._blocked_reason)
                endpoint = validate_endpoint(endpoint)
                config, targets = self._load(endpoint, model)
                family = targets[model]
                roles = {"text": None, "embedding": "embedding", "image": "analytics_image"}
                if kind not in roles:
                    raise PriceVerificationError("Unsupported paid operation")
                validate_model_eligibility(model, agent=roles[kind], base_model=family)
                prefixes = {"embedding": "text-embedding-", "image": "gpt-image-"}
                if (kind in prefixes and model not in config.get("deployment_models", {})
                        and not family.startswith(prefixes[kind])):
                    raise PriceVerificationError("Declare the underlying embedding/image family in deployment_models")
                profile = self._profile(config, model, family, endpoint)
                key = (endpoint.lower(), model, kind, tuple(tools), image_size)
                if key in self._verified:
                    return copy.deepcopy(self._verified[key])
                now = self._now().astimezone(timezone.utc)
                row = config.get("pricing", {}).get(model)
                source = config.get("pricing_sources", {}).get(model, {})
                automatic_embedding = (kind == "embedding" and family in EMBEDDING_SKUS
                                       and profile[1] == "global-standard"
                                       and source.get("verification") != "manual")
                if kind == "text" and family in MODEL_VERSIONS or automatic_embedding:
                    report_key = (profile, family if automatic_embedding else "text")
                    report_targets = {alias: target for alias, target in targets.items()
                                      if (target == family if automatic_embedding else target in MODEL_VERSIONS)}
                    if report_key not in self._reports:
                        try:
                            self._reports[report_key] = lookup_pricing(
                                *profile, report_targets, fetch_page=self._fetch_page, now=now,
                            )
                        except Exception as exc:
                            self._reports[report_key] = exc
                    report = self._reports[report_key]
                    if isinstance(report, Exception):
                        raise PriceVerificationError(f"Microsoft retail price refresh failed ({type(report).__name__})")
                    entry = report["deployments"][model]
                    if automatic_embedding:
                        rates = self._rates({"input": entry.get("input")}, ("input",))
                        reviewed = self._rates(row, ("input",))
                        if reviewed != rates:
                            raise PriceVerificationError("Current retail prices differ from reviewed rates")
                    else:
                        required = ("input", "cached", "output", "cache_write")
                        rates = self._rates({"long_context_threshold": report["long_context_threshold"],
                                             **entry["tiers"]}, required, tiered=True)
                        reviewed = self._rates(row, required, tiered=True)
                        if (reviewed["long_context_threshold"] != rates["long_context_threshold"]
                                or any(reviewed[tier][part] != rates[tier][part]
                                       for tier in ("short", "long") for part in required)):
                            raise PriceVerificationError("Current retail prices differ from reviewed rates")
                    source = {**{name: value for name, value in report.items() if name != "deployments"},
                              **entry, "verification": "retail", "azure_endpoint": endpoint}
                else:
                    source = config.get("pricing_sources", {}).get(model, {})
                    self._manual_source(
                        source, family, endpoint, profile, now,
                        unit=("USD per million tokens; image USD per generated image"
                              if kind == "image" else "USD per million tokens"),
                    )
                    if kind == "embedding":
                        required, tiered = ("input",), False
                    elif kind == "image":
                        if source.get("image_size") != image_size or source.get("image_quality") != "auto":
                            raise PriceVerificationError("Manual image rates must cover the requested size and auto quality")
                        required, tiered = ("input", "cached", "output", "image"), False
                    elif kind == "text":
                        version = re.match(r"gpt-(\d+)(?:\.(\d+))?", family)
                        writes = version and (int(version[1]) >= 6
                                              or int(version[1]) == 5 and int(version[2] or 0) >= 6)
                        required = ("input", "cached", "output") + (("cache_write",) if writes else ())
                        tiered = bool(writes or isinstance(row, dict) and ("short" in row or "long" in row))
                    else:
                        raise PriceVerificationError("Unsupported paid operation")
                    rates = self._rates(row, required, tiered=tiered)
                tool_prices = {}
                for tool in tools:
                    if tool != "web_search":
                        raise PriceVerificationError("Unsupported hosted tool pricing")
                    evidence = config.get("pricing_tool_sources", {}).get(tool, {})
                    self._manual_source(evidence, tool, endpoint, profile, now, unit="USD per 1000 calls")
                    fee = self._rates(config.get("pricing_tools", {}).get(tool), ("per_1000_calls",))
                    tool_prices[tool] = {"rates": fee, "source": evidence}
                self.checks.append({
                    "checked_at": now.isoformat(), "config_sha256": self._signature,
                    "deployment": model, "kind": kind, "rates": copy.deepcopy(rates),
                    "source": copy.deepcopy(source), "tools": copy.deepcopy(tool_prices),
                })
                self._persist()
                self._verified[key] = copy.deepcopy(rates)
                print(f"Pricing verified for {model} ({profile[0]}, {profile[1]}): "
                      f"{json.dumps(rates, sort_keys=True)} "
                      f"{source['unit']} ({source['verification']}).",
                      flush=True)
                if tool_prices:
                    print(f"Verified hosted-tool fees (USD per 1000 calls): "
                          f"{ {tool: item['rates']['per_1000_calls'] for tool, item in tool_prices.items()} }",
                          flush=True)
                return copy.deepcopy(rates)
            except Exception as exc:
                message = str(exc)
                self._blocked_reason = message
                if message not in self._errors:
                    self._errors.add(message)
                    print(f"AI request blocked by price verification: {message}. "
                          "Use fetch-pricing to create a new priced configuration, review it, and start a new run; "
                          "unsupported models/tools require current manual evidence.", file=sys.stderr)
                raise PriceVerificationError(message) from exc

    def _persist(self):
        if self.log_dir is None or self._written == len(self.checks):
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with (self.log_dir / "azure_price_checks.jsonl").open("a", encoding="utf-8") as file:
            for check in self.checks[self._written:]:
                file.write(json.dumps(check, ensure_ascii=False) + "\n")
        self._written = len(self.checks)

    def flush(self, log_dir):
        with self._lock:
            target = Path(log_dir)
            if target != self.log_dir:
                self._written = 0
                self.log_dir = target
            self._persist()
