"""Opt-in metadata-only search against the fixed Visual Studio Marketplace API."""
import json
import re

import httpx
from fastapi import HTTPException


def search(query, transport=None):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 100 or any(ord(c) < 32 for c in query):
        raise HTTPException(422, "Informe uma busca entre 2 e 100 caracteres.")
    payload = {
        "filters": [{
            "criteria": [{"filterType": 8, "value": query.strip()}],
            "pageNumber": 1, "pageSize": 20, "sortBy": 0, "sortOrder": 0,
        }],
        # Include only version metadata (IncludeVersions); no asset flags/URLs.
        "assetTypes": [], "flags": 1,
    }
    try:
        with httpx.Client(timeout=8, trust_env=False, follow_redirects=False, transport=transport) as client:
            with client.stream(
                "POST",
                "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery?api-version=7.2-preview.1",
                json=payload,
                headers={"Accept": "application/json;api-version=7.2-preview.1",
                         "Content-Type": "application/json"},
            ) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes(65536):
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ValueError("response too large")
                data = json.loads(raw)
        results = data.get("results") if isinstance(data, dict) else None
        extensions = results[0].get("extensions") if isinstance(results, list) and results else None
        if not isinstance(extensions, list):
            raise ValueError("invalid marketplace result")
        items = []
        for item in extensions[:20]:
            if not isinstance(item, dict) or not isinstance(item.get("publisher"), dict):
                continue
            publisher = item["publisher"].get("publisherName")
            name = item.get("extensionName")
            if not isinstance(publisher, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", publisher):
                continue
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name):
                continue
            versions = item.get("versions", [])
            version = versions[0].get("version") if versions and isinstance(versions[0], dict) else None
            items.append({
                "id": publisher + "." + name,
                "publisher": publisher,
                "name": name,
                "display_name": str(item.get("displayName") or name)[:200],
                "description": str(item.get("shortDescription") or "")[:500],
                "version": str(version or "")[:80],
                "source": "Visual Studio Marketplace",
                "install_enabled": False,
            })
        return {"items": items, "source": "Visual Studio Marketplace",
                "metadata_only": True, "downloaded": False}
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError):
        raise HTTPException(502, "Não foi possível consultar o catálogo público do VS Code.") from None
