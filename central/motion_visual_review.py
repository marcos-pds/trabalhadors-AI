"""Vision review of a planned scene against its master and neighboring frame."""
import json
import re

import httpx


class VisualReviewError(RuntimeError):
    pass


def _part(data_url):
    match = re.fullmatch(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)', data_url or '')
    if not match or len(match.group(2)) > 8_000_000:
        raise VisualReviewError('A imagem de revisão é inválida ou grande demais.')
    return {'inlineData': {'mimeType': match.group(1), 'data': match.group(2)}}


def review_scene(image, master, previous, *, title, action, visual_bible, api_key,
                 model='gemini-3.1-flash-lite', client=None):
    """Return observations, never a claim of guaranteed visual correctness."""
    if not api_key or not re.fullmatch(r'[A-Za-z0-9._-]+', model):
        raise VisualReviewError('O revisor visual precisa de um modelo Gemini configurado.')
    prompt = (
        'You are the visual continuity reviewer for a vertical animated episode. '
        'Image 1 is the generated scene; image 2 is the character master; '
        'image 3, when present, is the preceding scene. Compare visible evidence only. '
        'Check character identity only when that character is requested or visibly present. '
        'Do not demand every element of the visual bible in every scene. Compare architecture '
        'and props with the preceding frame only when available. Check anatomy/distortions '
        'and whether a visible state explicitly requested by this scene appears. Camera motion, '
        'light flicker and sound cannot be judged from a single still; do not mark them missing. '
        'Return strict JSON with status "pass" or "needs_revision" and '
        'findings as an array of at most 4 short Portuguese strings. Mark needs_revision '
        'only for a clear, material mismatch. '
        f'Title: {title[:120]}. Action: {action[:1024]}. Visual bible: {visual_bible[:1200]}.'
    )
    parts = [{'text': prompt}, _part(image), _part(master)]
    if previous:
        parts.append(_part(previous))
    sender = client or httpx.Client(timeout=90)
    try:
        response = sender.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            headers={'x-goog-api-key': api_key},
            json={'contents': [{'role': 'user', 'parts': parts}],
                  'generationConfig': {'responseMimeType': 'application/json', 'maxOutputTokens': 512}},
        )
        response.raise_for_status()
        text = ''.join(part.get('text', '') for part in
                       response.json()['candidates'][0]['content']['parts'])
        answer = json.loads(text)
        if isinstance(answer, list) and len(answer) == 1 and isinstance(answer[0], dict):
            answer = answer[0]
        if not isinstance(answer, dict):
            raise ValueError('invalid review object')
        status = answer.get('status')
        findings = answer.get('findings')
        if status not in ('pass', 'needs_revision') or not isinstance(findings, list) or any(
                not isinstance(item, str) for item in findings):
            raise ValueError('invalid review')
        visible_findings = [item.strip()[:240] for item in findings[:4] if item.strip()]
        visible_findings = [item for item in visible_findings if not re.search(
            r'(c[aâ]mera|camera).{0,40}(movimento|motion|avan[çc]|executad)|(?:movimento|motion|avan[çc]).{0,40}(c[aâ]mera|camera)', item, re.I)]
        if not re.search(r'\b(shadow|sombra|silhouette|silhueta|person|personagem|human|humano)\b', action, re.I):
            visible_findings = [item for item in visible_findings if not re.search(
                r'(aus[êe]ncia|falta|missing|n[aã]o aparece).{0,45}(sombra|silhueta|personagem)', item, re.I)]
        if not visible_findings:
            status = 'pass'
        return {'status': status, 'findings': visible_findings,
                'reviewer': model}
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise VisualReviewError('O revisor visual não conseguiu avaliar a cena. A imagem foi preservada.') from exc
    finally:
        if client is None:
            sender.close()
