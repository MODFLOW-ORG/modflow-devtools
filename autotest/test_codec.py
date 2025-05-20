from pprint import pprint

import pytest

import modflow_devtools.models as models
from modflow_devtools.codec import make_parser

MODELS = [name for name in models.get_models().keys() if name.startswith("mf6/")]
PARSER = make_parser()


@pytest.mark.parametrize("model_name", MODELS)
def test_parser(model_name, function_tmpdir):
    workspace = models.copy_to(function_tmpdir, model_name)
    nam_path = next(iter(workspace.glob("*.nam")))
    text = nam_path.open().read()
    pprint(text)
    tree = PARSER.parse(text)
    print(tree.pretty())
