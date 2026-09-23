import glob, sys, os, warnings; warnings.filterwarnings("ignore")
from inspect_ai.log import read_eval_log, write_eval_log
from inspect_ai import score
from inspect_evals.utils.aime_common import aime_scorer
import inspect_evals.utils.aime_common as m
print("scorer source:", m.__file__)
tag = sys.argv[1]; os.makedirs("/tmp/replay/aime", exist_ok=True)
for f in sorted(glob.glob("/tmp/lintrun/logs/main/*aime2024*.eval") + glob.glob("/tmp/step2/logs/*aime2025*.eval")):
    log = read_eval_log(f)
    new = score(log, aime_scorer(), action="overwrite", display="none", model="mockllm/model")
    out = f"/tmp/replay/aime/{tag}__{os.path.basename(f)}"
    write_eval_log(new, out); print(tag, os.path.basename(f)[:60], len(new.samples))
