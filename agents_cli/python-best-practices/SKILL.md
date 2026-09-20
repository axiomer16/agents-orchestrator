---
name: python-best-practices
description: Conventions Python modernes (typage, structure, tests).
---

# Python best practices

- Utiliser les type hints partout, `from __future__ import annotations` si besoin.
- Préférer `pathlib` à `os.path`.
- Une fonction = une responsabilité, pas plus de 40 lignes.
- Chaque module public a des tests dans `tests/` avec pytest.
