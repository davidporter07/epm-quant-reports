import requests, json

HOST = "http://100.101.63.65:11434"

print("\n=== qwen3.5:4b  no format, think disabled via /no_think prefix ===")
body = {
    "model": "qwen3.5:4b",
    "messages": [
        {"role": "system", "content": "/no_think\nReturn ONLY valid JSON. No markdown."},
        {"role": "user", "content": 'Return: {"color": "blue", "count": 3}'},
    ],
    "stream": False,
    "options": {"temperature": 0, "num_predict": 100, "num_ctx": 512},
}
resp = requests.post(f"{HOST}/api/chat", json=body, timeout=120)
content = resp.json()["message"]["content"]
print("Raw:", repr(content[:400]))

print("\n=== qwen3.5:4b  format json + think:false option ===")
body2 = {
    "model": "qwen3.5:4b",
    "messages": [
        {"role": "system", "content": "Return ONLY valid JSON. No markdown."},
        {"role": "user", "content": 'Return: {"color": "blue", "count": 3}'},
    ],
    "stream": False,
    "format": "json",
    "think": False,
    "options": {"temperature": 0, "num_predict": 100, "num_ctx": 512},
}
resp2 = requests.post(f"{HOST}/api/chat", json=body2, timeout=120)
content2 = resp2.json()["message"]["content"]
print("Raw:", repr(content2[:400]))

print("\n=== qwen3.5:4b  no format, no think key, see raw thinking output ===")
body3 = {
    "model": "qwen3.5:4b",
    "messages": [
        {"role": "system", "content": "Return ONLY valid JSON. No markdown."},
        {"role": "user", "content": 'Return: {"color": "blue", "count": 3}'},
    ],
    "stream": False,
    "options": {"temperature": 0, "num_predict": 200, "num_ctx": 512},
}
resp3 = requests.post(f"{HOST}/api/chat", json=body3, timeout=120)
rj3 = resp3.json()
content3 = rj3["message"]["content"]
thinking3 = rj3["message"].get("thinking", "")
print("Raw content:", repr(content3[:400]))
print("Thinking field:", repr(str(thinking3)[:200]))
print("Full message keys:", list(rj3["message"].keys()))
