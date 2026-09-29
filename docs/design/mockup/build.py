from pathlib import Path
root = Path(__file__).parent
src = root / 'src'
html = (src / 'shell.html').read_text(encoding='utf-8')
css = (src / 'styles.css').read_text(encoding='utf-8')
js = '\n'.join((src / f).read_text(encoding='utf-8') for f in ('data.js', 'app.js', 'viewer.js'))
out = html.replace('/*CSS*/', css).replace('/*JS*/', js)
(root / 'vitals-redesign.html').write_text(out, encoding='utf-8')
print(len(out))
