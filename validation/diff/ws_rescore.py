import sys, warnings; warnings.filterwarnings("ignore")
from inspect_ai.log import read_eval_log, write_eval_log
from inspect_ai import score
from inspect_evals.worldsense.worldsense import pattern_with_metadata
import inspect_evals.worldsense._utils as u; print("metrics source:", u.__file__)
log = read_eval_log(sys.argv[1])
new = score(log, pattern_with_metadata(r"^\(?\s*(1|2|3|TRUE|FALSE|IMPOSSIBLE|POSSIBLE)\s*\)?"), action="overwrite", display="none", model="mockllm/model")
write_eval_log(new, sys.argv[2])
