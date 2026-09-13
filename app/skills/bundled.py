"""Read the first-party catalog without importing the gateway or loading a model."""

from pathlib import Path


def list_bundled_skills() -> list[dict[str, str]]:
    root = Path(__file__).resolve().parents[1] / "bundled_skills"
    skills = []
    for path in sorted(root.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        metadata = {}
        for line in text.split("---", 2)[1].splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip().strip('"')
        example = next((line.removeprefix("Example request: ") for line in text.splitlines()
                        if line.startswith("Example request: ")), "")
        skills.append({"name": metadata["name"], "description": metadata["description"],
                       "example": example, "path": str(path)})
    return skills
