import io

p = 'models/ai_assistant.py'
s = io.open(p, encoding='utf-8').read()
old = "fname = g.split(':')"
new = "fname = next(iter(g.split(':')))"
with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(s.replace(old, new))
print('replaced')
