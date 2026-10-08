#!/usr/bin/env python3
"""Count nodes/arcs of the intermodal-20 network used by the CAIE solver (run via run_a3.sh image)."""
import json, os, sys
sys.path.insert(0, "/app"); os.chdir("/app")
import pandas as pd
from lib.config import OPTIMIZATION_PARAMS
from lib.intermodal_base_lib import Intermodal
nodes = pd.read_csv("data/intermodal-20.csv")
im = Intermodal("stats", [{"i": 1, "o": "Seattle WA", "d": "Orlando FL", "T": 48, "v": 200, "w": 2800}],
                dict(OPTIMIZATION_PARAMS))
print(json.dumps({"n_nodes": len(nodes), "by_type": nodes["type"].value_counts().to_dict(),
                  "arcs": {m: im.G[m].number_of_edges() for m in im.G},
                  "warehouses": nodes.loc[nodes.type == "H", "city"].tolist()}))
