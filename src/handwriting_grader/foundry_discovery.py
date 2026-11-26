"""Read-only Foundry resource discovery through Azure Resource Manager."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from azure.identity import DefaultAzureCredential

from .azure_ai import validate_endpoint
from .discovery import validate_model_eligibility
from .pricing import MODEL_VERSIONS, lookup_pricing, priced_config, write_new_config


MANAGEMENT = "https://management.azure.com"
ACCOUNT_API = "2024-10-01"
SUBSCRIPTION_API = "2022-12-01"
ACCOUNT_ID = re.compile(
    r"^/subscriptions/([0-9a-fA-F-]{36})/resourceGroups/([A-Za-z0-9_.()\-]+)/providers/"
    r"Microsoft\.CognitiveServices/accounts/([A-Za-z0-9_.\-]+)(?:/projects/[A-Za-z0-9_.\-]+)?$", re.I,
)
TEXT_ROLES = ("annotation", "marking_scheme", "ocr", "batch_metadata_ocr",
              "grading", "batch_grading", "moderation", "analytics", "student_feedback")
SKU_TYPES = {"globalstandard": "global-standard", "datazonestandard": "data-zone-standard"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Azure management redirects are not accepted")


def _management_page(url, credential):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "management.azure.com"
            or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment):
        raise ValueError("Azure management requests must stay on management.azure.com")
    token = credential.get_token("https://management.azure.com/.default").token
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with build_opener(_NoRedirect()).open(request, timeout=30) as response:
        body = response.read(6 * 1024 * 1024 + 1)
    if len(body) > 6 * 1024 * 1024:
        raise ValueError("Azure management response exceeds the response budget")
    return json.loads(body)


def _list_pages(url, credential, fetch_page):
    expected_path = urlsplit(url).path.lower()
    seen, items = set(), []
    while url:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "management.azure.com"
                or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment
                or parsed.path.lower() != expected_path or url in seen or len(seen) >= 100):
            raise ValueError("Invalid or repeated Azure management pagination link")
        seen.add(url)
        page = fetch_page(url, credential)
        if not isinstance(page, dict) or not isinstance(page.get("value"), list):
            raise ValueError("Malformed Azure management list response")
        items.extend(page["value"])
        url = page.get("nextLink")
        if url is not None and not isinstance(url, str):
            raise ValueError("Invalid Azure management pagination link")
    return items


def discover_foundry(resource, *, credential=None, fetch_page=None):
    """Find one account by name or account/project ARM ID, then list deployments."""
    fetch_page = fetch_page or _management_page
    own_credential = credential is None
    credential = credential or DefaultAzureCredential()
    try:
        match = ACCOUNT_ID.fullmatch(resource)
        if match:
            account_id = resource[:match.end(3)]
            account = fetch_page(f"{MANAGEMENT}{account_id}?api-version={ACCOUNT_API}", credential)
        else:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", resource):
                raise ValueError("Supply a Foundry account name or its account/project ARM resource ID")
            subscriptions = _list_pages(
                f"{MANAGEMENT}/subscriptions?api-version={SUBSCRIPTION_API}", credential, fetch_page,
            )
            accounts = []
            for subscription in subscriptions:
                sub_id = subscription.get("subscriptionId")
                if not isinstance(sub_id, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", sub_id):
                    raise ValueError("Azure returned an invalid subscription ID")
                accounts.extend(_list_pages(
                    f"{MANAGEMENT}/subscriptions/{sub_id}/providers/Microsoft.CognitiveServices/accounts"
                    f"?api-version={ACCOUNT_API}", credential, fetch_page,
                ))
            matches = [item for item in accounts if isinstance(item, dict)
                       and str(item.get("name", "")).lower() == resource.lower()]
            if not matches:
                raise ValueError("No matching Foundry account was found in accessible subscriptions")
            if len(matches) != 1:
                raise ValueError("Multiple accounts match; select an account ARM resource ID: "
                                 + ", ".join(str(item.get("id")) for item in matches))
            account = matches[0]
            account_id = account.get("id")
        if not isinstance(account, dict) or not isinstance(account_id, str) or not ACCOUNT_ID.fullmatch(account_id):
            raise ValueError("Azure returned an invalid Foundry account")
        properties = account.get("properties") or {}
        endpoints = properties.get("endpoints") or {}
        endpoint = (endpoints.get("OpenAI Language Model Instance API")
                    or endpoints.get("OpenAI") or properties.get("endpoint"))
        endpoint = validate_endpoint(endpoint)
        region = account.get("location")
        if not isinstance(region, str) or not re.fullmatch(r"[a-z][a-z0-9]{1,63}", region):
            raise ValueError("Azure did not return a valid resource region")
        deployments = _list_pages(
            f"{MANAGEMENT}{account_id}/deployments?api-version={ACCOUNT_API}", credential, fetch_page,
        )
        return {"resource_id": account_id, "endpoint": endpoint, "region": region,
                "deployments": deployments}
    finally:
        if own_credential:
            credential.close()


def _candidate(deployment, role):
    if not isinstance(deployment, dict):
        raise ValueError("Malformed Azure deployment")
    props = deployment.get("properties") or {}
    model = props.get("model") or {}
    name, family = deployment.get("name"), model.get("name")
    if (not isinstance(name, str) or not isinstance(family, str)
            or str(model.get("format", "")).lower() != "openai"
            or props.get("provisioningState") != "Succeeded"):
        return False
    if role == "embedding" and not family.lower().startswith("text-embedding-"):
        return False
    if role == "analytics_image" and not family.lower().startswith("gpt-image-"):
        return False
    try:
        validate_model_eligibility(name, agent=role, base_model=family)
    except ValueError:
        return False
    return True


def prepare_foundry_config(foundry, *, text_deployment=None, embedding_deployment=None,
                           image_deployment=None, meter_region=None, price_lookup=lookup_pricing,
                           require_text_selection=True):
    deployments = foundry["deployments"]
    config = {"azure_openai": {"endpoint": foundry["endpoint"], "api_version": "v1"},
              "models": {}, "deployment_models": {},
              "deployment_versions": {},
              "foundry_discovery": {"resource_id": foundry.get("resource_id"),
                                    "resource_region": foundry["region"],
                                    "fetched_at": datetime.now(timezone.utc).isoformat()},
              "caching": {"enabled": False, "scope": "run", "agents": {}}, "pricing": {}}
    selected = {}
    for role, requested in (("grading", text_deployment), ("embedding", embedding_deployment),
                            ("analytics_image", image_deployment)):
        candidates = [item for item in deployments if _candidate(item, role)]
        if requested is not None:
            candidates = [item for item in candidates if item["name"] == requested]
            if not candidates:
                raise ValueError(f"No eligible {role} deployment named {requested!r}")
        if len(candidates) > 1:
            flag = {"grading": "text", "embedding": "embedding", "analytics_image": "image"}[role]
            message = (f"Multiple {role} deployments found: "
                       + ", ".join(item["name"] for item in candidates)
                       + f"; select one with --{flag}-deployment")
            if role == "grading" and require_text_selection:
                raise ValueError(message)
            print(message + " (stage left unconfigured).")
            continue
        if candidates:
            selected[role] = candidates[0]
    if not selected and require_text_selection:
        raise ValueError("No eligible text or embedding deployments were found")
    region = meter_region or foundry["region"]
    for role, deployment in selected.items():
        name = deployment["name"]
        family = deployment["properties"]["model"]["name"].lower()
        config["deployment_models"][name] = family
        config["deployment_versions"][name] = deployment["properties"]["model"].get("version")
        for stage in TEXT_ROLES if role == "grading" else (role,):
            config["models"][stage] = name
        sku = str((deployment.get("sku") or {}).get("name", "")).lower()
        mode = SKU_TYPES.get(sku)
        if mode:
            report = price_lookup(region, mode, {name: family})
            config = priced_config(config, report)
            if family in MODEL_VERSIONS and deployment["properties"]["model"].get("version") != MODEL_VERSIONS[family]:
                config["pricing"][name] = {}
                print(f"{name} has a different or missing model version than the documented retail profile; "
                      "pricing remains UNPRICED.")
        else:
            config["pricing"][name] = {}
    return config


def report_foundry(resource, *, text_deployment=None, embedding_deployment=None,
                   image_deployment=None, meter_region=None, write_config=None):
    if write_config is not None and (Path(write_config).exists() or Path(write_config).is_symlink()):
        raise FileExistsError("The discovered configuration must be a new file")
    foundry = discover_foundry(resource)
    print(f"Foundry account: {foundry['resource_id']}")
    print(f"Endpoint: {foundry['endpoint']}; resource region: {foundry['region']}")
    reports = {}

    def cached_price(region, mode, models):
        name, family = next(iter(models.items()))
        key = (region, mode, name, family)
        if key not in reports:
            reports[key] = lookup_pricing(region, mode, models)
        return reports[key]

    for item in foundry["deployments"]:
        props = item.get("properties") or {}
        model = props.get("model") or {}
        print(f"Deployment: {item.get('name')}; model={model.get('name')}; version={model.get('version')}; "
              f"format={model.get('format')}; SKU={(item.get('sku') or {}).get('name')}; "
              f"state={props.get('provisioningState')}")
        if props.get("capabilities"):
            print(f"  Reported capabilities: {props['capabilities']}")
        if any(_candidate(item, role) for role in ("grading", "embedding", "analytics_image")):
            mode = SKU_TYPES.get(str((item.get("sku") or {}).get("name", "")).lower())
            if mode:
                family = model["name"].lower()
                report = cached_price(meter_region or foundry["region"], mode, {item["name"]: family})
                entry = report["deployments"][item["name"]]
                version_matches = family not in MODEL_VERSIONS or model.get("version") == MODEL_VERSIONS[family]
                source = entry.get("source") or (report["source"] if report["pages_fetched"] else "not queried")
                print(f"  Retail: {entry['status'] if version_matches else 'UNPRICED (model version mismatch)'}; "
                      f"rates={entry.get('tiers') or entry.get('input') or 'none'}; "
                      f"source={source}")
                if (not meter_region and foundry["region"] != "eastus" and mode == "global-standard"
                        and entry["status"] != "PRICED" and version_matches):
                    alternative = cached_price("eastus", mode, {item["name"]: family})["deployments"][item["name"]]
                    rates = alternative.get("tiers") or alternative.get("input")
                    print(f"  Alternative eastus retail profile: "
                          f"{rates if alternative['status'] == 'PRICED' else 'UNPRICED'} "
                          "(not selected; review and use --meter-region eastus).")
            else:
                print("  Retail: UNPRICED (unsupported deployment SKU)")
    config = prepare_foundry_config(foundry, text_deployment=text_deployment,
                                    embedding_deployment=embedding_deployment, image_deployment=image_deployment,
                                    meter_region=meter_region, price_lookup=cached_price,
                                    require_text_selection=write_config is not None)
    print(f"Suggested stage deployments: {config['models']}")
    print(f"Retail meter region: {meter_region or foundry['region']} (resource location may differ from meter profile).")
    for name in config["deployment_models"]:
        source = config.get("pricing_sources", {}).get(name, {})
        status = source.get("status", "UNPRICED") if config["pricing"].get(name) else "UNPRICED"
        print(f"Retail pricing for {name}: {status}; rates={config['pricing'].get(name) or 'none'}")
        if source:
            print(f"  Source: {source.get('source')}; fetched: {source.get('fetched_at')}")
            for issue in source.get("issues", []):
                print(f"  UNPRICED: {issue}")
    print("Retail prices are estimates, not contract charges. Deployment metadata does not verify "
          "image capability, quota, quality or permission to send student data.")
    if write_config is not None:
        write_new_config(write_config, config)
        print(f"New configuration: {write_config}; review it before use.")
    print("No model inference was performed. Each paid stage still requires its own data/cost approval.")
    return config
