"""Puppeteer stage rack: stages, tools, reports, cache keys, branching, costs and presets.

Importing the package registers every built-in tool. See docs/STAGES.md.
"""
from .base import STAGES,PREP_STAGES,GENERATION_STAGES,LABELS,Tool,OffTool,register,get_tool,tools_for,registry,fresh
from . import input_doctor,audio,depth,mask,composite,face,prompt,generate,finish   # noqa: F401  (registration)
from .calls import OfflineError,record_call,offline,read_calls,total_cost
from .report import write_report,read_report,all_reports,new_report
from .cache import cache_key,artifact_hash,hash_artifacts
from .runner import run_chain,run_mode,load_run,save_run
from .branch import branch,run_branch,tree,describe_change,changed_chain
from .presets import chain_for_mode,mode_for_chain,normalize_chain,list_presets,get_preset,save_preset,describe_chain,paid_stages
from .migrate import reconstruct,run_info
from . import costs
from . import editlayer,masktrack,meshedit,words   # noqa: F401  (edit layer + its track hooks; Agents 2–4 replace the stubs)
from . import imports,subtitles   # noqa: F401  (Import my own tools, registered after every stage's own tools; subtitles from the Words track)
from .editlayer import register_track

__all__=['STAGES','PREP_STAGES','GENERATION_STAGES','LABELS','Tool','OffTool','register','get_tool','tools_for','registry','fresh','OfflineError','record_call','offline','read_calls','total_cost',
         'write_report','read_report','all_reports','new_report','cache_key','artifact_hash','hash_artifacts','run_chain','run_mode','load_run','save_run','branch','run_branch','tree','describe_change','changed_chain',
         'chain_for_mode','mode_for_chain','normalize_chain','list_presets','get_preset','save_preset','describe_chain','paid_stages','reconstruct','run_info','costs','editlayer','register_track']
