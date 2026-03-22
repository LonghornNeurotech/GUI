# ASSR Collaboration Workspace

This folder is a snapshot of the ASSR-integrated GUI workspace for collaborative editing in Cursor/Claude.

## Open in Cursor/Claude

Open this folder directly:

- `collaborations/assr_workspace_v1`

## Run locally

```bash
conda create -y -n neurable313 python=3.13
conda activate neurable313
cd collaborations/assr_workspace_v1
python -m pip install -r requirements.txt
python GUI.py
```

## ASSR task entry point

In the GUI task dropdown, select:

- `ASSR Task`

## Collaboration flow

1. Create a feature branch from `neurable`
2. Make edits in this subfolder
3. Commit and push your branch
4. Open a PR into `neurable`

