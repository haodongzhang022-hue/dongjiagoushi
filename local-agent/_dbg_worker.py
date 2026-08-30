import sys; sys.path.insert(0, '.')
from hybrid.worker import LocalWorker
import os
print('os.name:', os.name)
w = LocalWorker(root_dir='/mnt/e/1shuju/dongjiagoushi/dongjiagoushi')
print('picked bash:', w._pick_bash())
r = w.run_one('local-agent/tests/test_data_layer.sh')
print('exit:', r['exit_code'], 'dur:', r['duration'])
print('out:', r['output'][:500].replace(chr(10),' | '))