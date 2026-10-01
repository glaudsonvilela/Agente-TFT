"""Whole-tree structural inventory, not a claim of line-by-line semantic review.

Only tracked source/TOML files are read. No config rewriting, autofix or deletion.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib


def audit(root, paths):
    root=Path(root).resolve()
    counts=Counter(); findings=[]; errors=[]; functions=defaultdict(list)
    manifests={}; crates={}
    for name in sorted(paths):
        path=root/name
        if not path.is_file() or not path.resolve().is_relative_to(root): continue
        suffix=path.suffix
        if suffix not in {'.py','.rs','.toml'}: continue
        counts[suffix]+=1
        text=path.read_text(encoding='utf-8')
        if len(text.encode())>2*1024*1024:
            errors.append(dict(path=name,kind='source_budget'));continue
        if suffix=='.py':
            try: tree=ast.parse(text,filename=name)
            except SyntaxError as e:
                errors.append(dict(path=name,kind='python_syntax',line=e.lineno));continue
            if '/tests/' not in '/'+name:
                for n in ast.walk(tree):
                    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and getattr(n,'end_lineno',n.lineno)-n.lineno>=20:
                        body=ast.dump(n,include_attributes=False)
                        functions[hashlib.sha256(body.encode()).hexdigest()].append(dict(path=name,line=n.lineno,name=n.name))
            if 'raw.communitydragon.org/latest/' in text:
                findings.append(dict(path=name,kind='legacy_mutable_asset_reference',note='inspect call path; release adapter pins new outputs'))
        elif suffix=='.toml':
            try: document=tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                errors.append(dict(path=name,kind='toml_syntax'));continue
            if path.name=='Cargo.toml':
                manifests[name]=document
                if 'package' in document: crates[str(path.parent.resolve())]=document['package']['name']
        elif suffix=='.rs' and '/tests/' not in '/'+name:
            # Best-effort inventory only: test modules are excluded at their first cfg.
            production=text.split('#[cfg(test)]',1)[0]
            if re.search(r'TFT\d+[_A-Za-z]',production):
                findings.append(dict(path=name,kind='season_literal_review',note='review whether data or intentional adapter; not automatically wrong'))
        if text.count('\n')>500:
            findings.append(dict(path=name,kind='large_module_review',lines=text.count('\n')+1))
    workspace=manifests.get('rust/Cargo.toml',{}).get('workspace',{}).get('members',[])
    if len(workspace)!=len(set(workspace)): errors.append(dict(path='rust/Cargo.toml',kind='duplicate_workspace_member'))
    for member in workspace:
        if 'rust/'+member+'/Cargo.toml' not in manifests:
            errors.append(dict(path=member,kind='missing_workspace_member'))
    edges=defaultdict(set)
    for name,m in manifests.items():
        if 'package' not in m: continue
        origin=m['package']['name']
        for section in ('dependencies','build-dependencies'):
            for dep in m.get(section,{}).values():
                if isinstance(dep,dict) and 'path' in dep:
                    target=str((root/name).parent.joinpath(dep['path']).resolve())
                    if target not in crates:
                        errors.append(dict(path=name,kind='missing_path_dependency',target=dep['path']))
                    else: edges[origin].add(crates[target])
    def visit(node,stack,done):
        if node in stack:
            errors.append(dict(kind='cargo_dependency_cycle',path=' -> '.join(stack+[node])));return
        if node in done:return
        for nxt in sorted(edges.get(node,set())):visit(nxt,stack+[node],done)
        done.add(node)
    done=set()
    for node in sorted(edges):visit(node,[],done)
    duplicates=[v for v in functions.values() if len(v)>1]
    return dict(schema_version=1,scope='all tracked Python/Rust/TOML: structural scan; detailed semantic review remains scoped',
        full_semantic_review=False,files=dict(counts),workspace_members=len(workspace),local_crates=len(crates),
        errors=errors,findings=findings,potential_copied_functions=duplicates,files_modified=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('.'));p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    result=subprocess.run(['git','-C',str(a.root),'ls-files','-z'],capture_output=True,check=True,timeout=10)
    paths=[x for x in result.stdout.decode().split('\0') if x]
    report=audit(a.root,paths)
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print('CODE_REVIEW='+json.dumps(dict(files=report['files'],workspace_members=report['workspace_members'],
        errors=len(report['errors']),findings=len(report['findings']),full_semantic_review=False,report=str(a.output))))
    if report['errors']:raise SystemExit(2)

if __name__=='__main__':main()
