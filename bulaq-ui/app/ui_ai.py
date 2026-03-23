import json
import os
from datetime import UTC, datetime

import requests

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL_DEFAULT = os.getenv("AI_MODEL", "gpt-5.4")


def chat_completions_call(
    api_key: str,
    model: str,
    system_prompt: str,
    user_text: str,
    base_url: str,
    temperature: float = 0.2,
) -> dict:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": temperature,
        "max_tokens": 4096,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=90)
    r.raise_for_status()
    return r.json()


def extract_chat_completions_text(resp: dict) -> str:
    try:
        return resp["choices"][0]["message"]["content"]
    except Exception:
        return json.dumps(resp, ensure_ascii=False, indent=2)


def build_single_uuid_ai_payload(uuid: str, tag_item: dict, summary: dict, snapshot_rows: list, recent_events: list):
    anomaly_events = []
    for e in recent_events or []:
        if e.get("uuid") == uuid and e.get("kind") == "anomaly":
            anomaly_events.append(e)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "uuid_context": {
            "uuid": uuid,
            "tag": tag_item or {},
            "summary": summary or {},
        },
        "recent_snapshot_rows": snapshot_rows[-80:] if snapshot_rows else [],
        "recent_anomaly_events": anomaly_events[:30],
    }


def run_ai_analysis_for_uuid(uuid: str, tag_item: dict, summary: dict, snapshot_rows: list, recent_events: list, model: str):
    payload = build_single_uuid_ai_payload(
        uuid=uuid,
        tag_item=tag_item,
        summary=summary,
        snapshot_rows=snapshot_rows,
        recent_events=recent_events,
    )

    system_prompt = """
You are an industrial anomaly-detection assistant focused on one UUID only.

Your job:
- analyze only the selected UUID
- use only the supplied evidence
- explain likely process, sensor/data-quality, or detector-related causes
- optionally suggest conservative per-UUID tuning

Rules:
1. Return ONLY valid JSON.
2. No markdown fences.
3. Do not mention any UUID other than the selected one.
4. Ground every claim in provided evidence.
5. Be conservative.
6. If evidence is weak, say "insufficient_evidence".
7. Distinguish clearly between:
   - likely_process_causes
   - likely_sensor_or_data_quality_causes
   - likely_detector_causes
8. If the UUID is not active or has no meaningful rows, say so explicitly.
9. Use detector reason fields when available.
10. You may suggest per-UUID tuning because this system supports per-UUID assignment/settings.

Return exactly this JSON shape:
{
  "uuid": string,
  "status": "healthy|anomalous|misconfigured|inactive|insufficient_evidence",
  "summary": string,
  "current_assignment_assessment": {
    "assigned_model": string,
    "enabled_for_scoring": boolean,
    "is_assignment_reasonable": "yes|no|unclear",
    "why": string
  },
  "evidence": {
    "snapshot_row_count": number,
    "recent_anomaly_count": number,
    "dominant_reasons": [string],
    "value_behavior": string,
    "score_behavior": string
  },
  "likely_process_causes": [string],
  "likely_sensor_or_data_quality_causes": [string],
  "likely_detector_causes": [string],
  "recommended_actions": [
    {
      "priority": "low|medium|high",
      "action_type": "inspect_process|inspect_sensor|inspect_signal_quality|leave_detector_unchanged|tune_detector|activate_scoring|assign_model",
      "action": string
    }
  ],
  "suggested_parameter_changes": [
    {
      "parameter": string,
      "current_value": string,
      "suggested_value": string,
      "rationale": string,
      "confidence": "low|medium|high"
    }
  ],
  "confidence": "low|medium|high"
}
""".strip()

    user_text = (
        "Analyze the following single-UUID anomaly context. "
        "Use only the provided evidence. Return only valid JSON.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )

    resp = chat_completions_call(
        api_key=AI_API_KEY,
        model=model,
        system_prompt=system_prompt,
        user_text=user_text,
        base_url=AI_BASE_URL,
        temperature=0.2,
    )
    raw_text = extract_chat_completions_text(resp)

    parsed = None
    try:
        parsed = json.loads(raw_text)
    except Exception:
        parsed = None

    return {
        "ok": True,
        "raw_text": raw_text,
        "parsed": parsed,
        "payload": payload,
    }