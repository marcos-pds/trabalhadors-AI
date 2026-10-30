"""Operator-only CLI for rendering a single approved FFmpeg manifest job."""
import argparse
import json
from pathlib import Path

from central.motion_ffmpeg import render_one


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve(strict=True)
    if manifest_path.stat().st_size > 256 * 1024:
        parser.error("Manifest exceeds local size limit")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list) or len(jobs) != 1:
        parser.error("Exactly one job is required")
    print("Projeto local:", args.project.resolve(strict=True))
    print("Job:", jobs[0].get("id"), "adapter:", jobs[0].get("adapter"))
    print("A renderizacao gera arquivo novo, usa FFmpeg e pode consumir CPU/disco.")
    if input("Digite RENDERIZAR para autorizar: ").strip() != "RENDERIZAR":
        print("Operacao nao autorizada; nenhum processo iniciado.")
        return 1
    result = render_one(payload, args.project, operator_approved=True, timeout=args.timeout)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
