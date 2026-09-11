"""Update only the three public Voice legal handlers; leave telephony intact."""
import ast
from pathlib import Path


def patch(source: str) -> str:
    routes = {"sms_program":("/sms-program","program"), "privacy_policy":("/privacy","privacy"), "sms_terms":("/terms","terms")}
    tree = ast.parse(source)
    replacements = []
    for name, (route, page) in routes.items():
        matches = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
        if len(matches) != 1:
            raise RuntimeError("Expected one reviewed Voice policy handler: " + name)
        node = matches[0]
        if not any(isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr=='get'
                   and d.args and isinstance(d.args[0],ast.Constant) and d.args[0].value==route for d in node.decorator_list):
            raise RuntimeError("Voice policy route changed: " + name)
        body = ("    from app.sms_policy import render_policy\n"
                f"    return HTMLResponse(render_policy({page!r}), headers={{'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'}})\n")
        replacements.append((node.body[0].lineno-1, node.end_lineno, body))
    lines = source.splitlines(keepends=True)
    for start, end, body in sorted(replacements, reverse=True):
        lines[start:end] = [body]
    result = ''.join(lines)
    compile(result, 'voice-main.py', 'exec')
    return result


def patch_nginx(current: str) -> str:
    marker = '        # Floodman public SMS policy aliases (customer-sms-v1)'
    if marker not in current:
        anchor = '        location = /floodman-login {'
        if current.count(anchor) != 1:
            raise RuntimeError('Expected one reviewed Hub routing anchor')
        aliases = marker + '\n' + ''.join(
            f'        location = /{page} {{ return 302 https://aicall.oninetwork.com/{page}; }}\n'
            for page in ('privacy','terms','sms-program')) + '\n'
        return current.replace(anchor, aliases+anchor)
    return current


if __name__ == '__main__':
    path = Path('/opt/voice/app/main.py')
    nginx = Path('/opt/floodman/aio/nginx.conf.template')
    voice_source = patch(path.read_text())
    nginx_source = patch_nginx(nginx.read_text())
    path.write_text(voice_source, encoding='utf-8')
    nginx.write_text(nginx_source, encoding='utf-8')
