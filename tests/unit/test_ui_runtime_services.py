from app.ui.runtime_services import extract_chat_response, parse_nvidia_smi_csv


def test_extract_chat_response_supports_redsight_shape():
    assert extract_chat_response({"message": "ready"}) == "ready"


def test_extract_chat_response_supports_openai_shape():
    payload = {"choices": [{"message": {"content": "hello"}}]}
    assert extract_chat_response(payload) == "hello"


def test_extract_chat_response_falls_back_cleanly():
    assert extract_chat_response({}) == "No response"
    assert extract_chat_response(None) == "No response"


def test_parse_nvidia_smi_csv_handles_dual_gpu_output():
    output = (
        "0, NVIDIA GeForce RTX 5090, 63, 8192, 32607, 55, 420.5\n"
        "1, NVIDIA GeForce RTX 5090, 41, 4096, 32607, 49, 310.25\n"
    )
    rows = parse_nvidia_smi_csv(output)
    assert len(rows) == 2
    assert rows[0]["index"] == "0"
    assert rows[0]["name"] == "NVIDIA GeForce RTX 5090"
    assert rows[0]["util"] == 63.0
    assert 25.0 < rows[0]["vram_percent"] < 26.0
    assert rows[1]["power"] == 310.25


def test_parse_nvidia_smi_csv_tolerates_zero_and_bad_numeric_fields():
    rows = parse_nvidia_smi_csv("0, GPU, N/A, broken, 0, N/A, N/A\n")
    assert rows == [
        {
            "index": "0",
            "name": "GPU",
            "util": 0.0,
            "used": 0.0,
            "total": 0.0,
            "vram_percent": 0.0,
            "temp": 0.0,
            "power": 0.0,
        }
    ]


def test_parse_nvidia_smi_csv_ignores_incomplete_rows():
    assert parse_nvidia_smi_csv("0, GPU, 50\n") == []
