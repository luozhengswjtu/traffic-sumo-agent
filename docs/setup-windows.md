# Windows Setup

This document describes the recommended Windows setup path for running TrafficAgent from source.

## 1. Install Conda

Use one of the following:

- Anaconda
- Miniconda
- Miniforge

The project is currently tested as a Windows-first Conda workflow.

## 2. Create the Python environment

From the repository root:

```powershell
conda env create -f environment.yml
conda activate traffic-agent
```

If you prefer a repo-local environment:

```powershell
conda env create -f environment.yml -p .\.conda
conda activate .\.conda
```

## 3. Install SUMO

Install SUMO separately on Windows. A typical install path is similar to:

```text
C:\Program Files\Eclipse\Sumo
```

After installation, expose SUMO to the current PowerShell session:

```powershell
$env:SUMO_HOME = "C:\Program Files\Eclipse\Sumo"
$env:PATH = "$env:SUMO_HOME\bin;$env:PATH"
$env:PYTHONPATH = "$env:SUMO_HOME\tools;$env:PYTHONPATH"
```

If you want these variables to persist, set them in your own Windows environment settings instead of only the current shell.

## 4. Verify the toolchain

Verify Python-side dependencies:

```powershell
python -c "import PySide6, pydantic; print('python deps ok')"
```

Verify SUMO executables:

```powershell
Get-Command sumo, sumo-gui, netconvert
```

Verify TraCI import:

```powershell
python -c "import traci; print('traci ok')"
```

If `traci` import fails, your `PYTHONPATH` likely does not include `$env:SUMO_HOME\tools`.

## 5. Start the application

```powershell
python app\main.py
```

On first launch, the app will create:

- `.traffic_agent/config/`
- `.traffic_agent/traffic_agent.db`
- `workspace/projects/`

## 6. Configure model access

The desktop app stores model settings at:

```text
.traffic_agent/config/model_config.json
```

You can either:

- Launch the app and fill the settings dialog
- Create the file manually using `docs/model_config.example.json`

## 7. Common Problems

### `sumo` or `sumo-gui` not found

Cause:

- SUMO `bin` directory is not on `PATH`

Fix:

```powershell
$env:PATH = "$env:SUMO_HOME\bin;$env:PATH"
```

### `traci` import fails

Cause:

- SUMO `tools` directory is not on `PYTHONPATH`

Fix:

```powershell
$env:PYTHONPATH = "$env:SUMO_HOME\tools;$env:PYTHONPATH"
```

### `netconvert` not found

Cause:

- SUMO toolchain is incomplete on `PATH`

Effect:

- Some code paths can write a placeholder network file as a fallback
- Full runnable simulation setup still requires a real `netconvert`

### API key not configured

Cause:

- `api_key` in `.traffic_agent/config/model_config.json` is empty

Effect:

- Model-backed assistant flows will fail

### PowerShell profile execution warnings

Cause:

- Local execution policy blocks profile scripts

Effect:

- Shell output may contain warning noise before the actual command output

Workaround:

- Run commands with `-NoProfile` when necessary

## 8. Scope Notes

- This repository does not currently ship a Windows installer
- This repository does not bundle SUMO binaries
- The primary supported path is running from source in a Conda environment
