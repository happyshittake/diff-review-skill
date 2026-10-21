"""Create a disposable real Git repository and start a browser-test session."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
repo = Path(tempfile.mkdtemp(prefix='review-demo-repo-'))

def git(*args):
    subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)


git('init', '-b', 'main')
git('config', 'user.name', 'Demo')
git('config', 'user.email', 'demo@example.invalid')
(repo / 'src').mkdir()
(repo / 'src/checkout.ts').write_text('export function checkout(items) {\n  const total = calculateTotal(items);\n  return createOrder({ items, total });\n}\n')
git('add', '.')
git('commit', '-m', 'initial')
(repo / 'src/checkout.ts').write_text('export function checkout(items) {\n  const validated = validateItems(items);\n  if (!validated.ok) {\n    throw new Error("Invalid cart");\n  }\n  const total = calculateTotal(validated.items);\n  return createOrder({ items, total });\n}\n')
(repo / 'src/validation.ts').write_text('export function validateItems(items) {\n  // <script>window.XSS = true</script>\n  return { ok: Array.isArray(items) && items.length > 0, items };\n}\n')
(repo / '.env').write_text('SECRET=never-display\n')
summaries = repo / '.git/summaries.json'
summaries.write_text(json.dumps({'overall': 'Menambahkan validasi cart sebelum checkout.\nReview konsistensi validated.items. Test aplikasi belum dijalankan (fixture demo).'}))
result = subprocess.check_output([sys.executable, str(ROOT / 'scripts/review.py'), 'start', '--repo', str(repo), '--summaries', str(summaries)])
info = json.loads(result)
info['demo_repo'] = str(repo)
print(json.dumps(info))
