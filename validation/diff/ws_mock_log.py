import warnings; warnings.filterwarnings("ignore")
from inspect_ai import eval as ev
from inspect_ai.model import get_model, ModelOutput
from inspect_evals.worldsense.worldsense import worldsense
t = worldsense(problemnames=["Infer.normal"], shuffle=False)
outs = [ModelOutput.from_content("mockllm/model", s.target.title()) for s in list(t.dataset)[:10]]
log = ev(t, model=get_model("mockllm/model", custom_outputs=outs), limit=10, display="none", log_dir="/tmp/replay/ws")[0]
print(log.location)
