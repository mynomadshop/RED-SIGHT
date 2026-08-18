"""
RedSight - API Documentation Generator

Generates comprehensive API documentation from the FastAPI application.
Usage:
    python scripts/api_docs.py              # Generate HTML docs
    python scripts/api_docs.py --output docs/api.html
    python scripts/api_docs.py --json       # Generate JSON schema
    python scripts/api_docs.py --markdown   # Generate Markdown docs
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def generate_openapi_json(app):
    """Generate OpenAPI JSON schema."""
    return app.openapi()


def generate_html_docs(app, output_path):
    """Generate HTML documentation from OpenAPI spec."""
    openapi_spec = app.openapi()
    
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RedSight API Documentation</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
        header {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            padding: 3rem 0;
            border-bottom: 2px solid #0f3460;
        }}
        h1 {{
            font-size: 2.5rem;
            color: #e94560;
            margin-bottom: 0.5rem;
        }}
        .subtitle {{ color: #a0a0a0; font-size: 1.1rem; }}
        .endpoint {{
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 8px;
            margin: 1.5rem 0;
            padding: 1.5rem;
        }}
        .method {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 4px;
            font-weight: bold;
            font-size: 0.875rem;
            margin-right: 1rem;
        }}
        .GET {{ background: #2d6a4f; color: white; }}
        .POST {{ background: #e94560; color: white; }}
        .PUT {{ background: #f4a261; color: black; }}
        .DELETE {{ background: #e76f51; color: white; }}
        .path {{ font-family: monospace; color: #00d4ff; }}
        .description {{ margin: 1rem 0; color: #b0b0b0; }}
        .params {{
            background: #0f0f0f;
            padding: 1rem;
            border-radius: 4px;
            margin-top: 1rem;
        }}
        .param {{
            display: flex;
            margin: 0.5rem 0;
            padding: 0.5rem;
            background: #1a1a1a;
            border-radius: 4px;
        }}
        .param-name {{
            font-family: monospace;
            color: #00d4ff;
            min-width: 150px;
        }}
        .param-type {{
            color: #a0a0a0;
            min-width: 100px;
        }}
        .tag {{
            background: #333;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            margin-top: 1rem;
        }}
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>RedSight API Documentation</h1>
            <p class="subtitle">High-Performance Local AI Intelligence Platform</p>
        </div>
    </header>
    <div class="container">
        <div class="info">
            <h2>Base URL</h2>
            <p><code>http://localhost:8000/api/v1</code></p>
        </div>
        {endpoints}
    </div>
</body>
</html>"""
    
    endpoints_html = ""
    for path, methods in openapi_spec.get("paths", {}).items():
        for method, details in methods.items():
            if method not in ["get", "post", "put", "delete"]:
                continue
            
            tags = details.get("tags", [])
            summary = details.get("summary", "")
            description = details.get("description", "")
            params = details.get("parameters", [])
            
            endpoints_html += f"""
        <div class="endpoint">
            <span class="method {method.upper()}">{method.upper()}</span>
            <span class="path">{path}</span>
            <div class="description">{summary}</div>
            {description and f'<div class="description">{description}</div>'}
            {tags and f'<div class="tag">Tags: {", ".join(tags)}</div>'}
            {params and generate_params_html(params)}
        </div>"""
    
    html = html_template.format(endpoints=endpoints_html)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"✅ HTML documentation generated: {output_path}")


def generate_params_html(params):
    """Generate HTML for parameters."""
    html = '<div class="params"><h3>Parameters</h3>'
    for param in params:
        name = param.get("name", "")
        ptype = param.get("schema", {}).get("type", "string")
        required = "required" if param.get("required") else "optional"
        html += f"""
            <div class="param">
                <span class="param-name">{name}</span>
                <span class="param-type">{ptype}</span>
                <span class="param-required">{required}</span>
            </div>"""
    html += "</div>"
    return html


def generate_markdown_docs(app, output_path):
    """Generate Markdown documentation."""
    openapi_spec = app.openapi()
    
    md = "# RedSight API Documentation\n\n"
    md += "## Base URL\n\n`http://localhost:8000/api/v1`\n\n"
    
    for path, methods in openapi_spec.get("paths", {}).items():
        for method, details in methods.items():
            if method not in ["get", "post", "put", "delete"]:
                continue
            
            tags = details.get("tags", [])
            summary = details.get("summary", "")
            description = details.get("description", "")
            params = details.get("parameters", [])
            
            md += f"### {method.upper()} {path}\n\n"
            md += f"**{summary}**\n\n"
            if description:
                md += f"{description}\n\n"
            if tags:
                md += f"Tags: {', '.join(tags)}\n\n"
            if params:
                md += "#### Parameters\n\n"
                md += "| Name | Type | Required | Description |\n"
                md += "|------|------|----------|-------------|\n"
                for param in params:
                    name = param.get("name", "")
                    ptype = param.get("schema", {}).get("type", "string")
                    required = "Yes" if param.get("required") else "No"
                    desc = param.get("description", "")
                    md += f"| `{name}` | {ptype} | {required} | {desc} |\n"
                md += "\n"
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)
    
    print(f"✅ Markdown documentation generated: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="RedSight API Documentation Generator")
    parser.add_argument("--output", "-o", default="docs/api.html", help="Output file path")
    parser.add_argument("--json", action="store_true", help="Generate JSON OpenAPI spec")
    parser.add_argument("--markdown", action="store_true", help="Generate Markdown docs")
    parser.add_argument("--html", action="store_true", help="Generate HTML docs (default)")
    args = parser.parse_args()
    
    if not any([args.json, args.markdown, args.html]):
        args.html = True
    
    # Import and create app
    try:
        from app.server import create_app
        app = create_app()
    except Exception as e:
        print(f"❌ Failed to create app: {e}")
        sys.exit(1)
    
    # Generate documentation
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    if args.json:
        spec = generate_openapi_json(app)
        json_path = output_path.with_suffix(".json") if args.html else output_path
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)
        print(f"✅ JSON OpenAPI spec generated: {json_path}")
    
    if args.html:
        generate_html_docs(app, str(output_path))
    
    if args.markdown:
        md_path = output_path.with_suffix(".md") if args.html else output_path
        generate_markdown_docs(app, str(md_path))


if __name__ == "__main__":
    main()
