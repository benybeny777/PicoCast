#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$Apply,
    [string]$BackupParent = (Join-Path $env:USERPROFILE '.codex\backups\picocast-python312'),
    [ValidateRange(1, 600)][int]$StopTimeoutSeconds = 30,
    [ValidateRange(1, 86400)][int]$OperationTimeoutSeconds = 3600
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = [Text.UTF8Encoding]::new($false)
if ($CheckOnly -and $Apply) { throw '[E-MIGRATION-ARGS] CheckOnly と Apply は併用できません。' }
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$environmentPath = Join-Path $workspace '.venv'
$oldEnvironment = Join-Path $workspace '.venv-311-backup'
$python = Join-Path $environmentPath 'Scripts\python.exe'
$helper = Join-Path $PSScriptRoot 'python312_switch.py'
$temporaryRoot = Join-Path $workspace 'temp\python312-switch'
$backupBase = [IO.Path]::GetFullPath($BackupParent)
if ($backupBase.StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase) -or $backupBase -ieq $workspace) {
    throw '[E-MIGRATION-BACKUP] 退避先はリポジトリ外に指定してください。'
}
foreach ($path in @($environmentPath, $oldEnvironment, $temporaryRoot)) {
    if (-not ([IO.Path]::GetFullPath($path)).StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw '[E-MIGRATION-PATH] 環境の操作先がワークスペース外です。'
    }
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw '[E-MIGRATION-PYTHON] 現在の .venv の Python がありません。' }
if (Test-Path -LiteralPath $oldEnvironment) { throw '[E-MIGRATION-PRESERVED] .venv-311-backup が既にあります。上書きせず停止します。' }
$environmentItem = Get-Item -LiteralPath $environmentPath
if ($environmentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '[E-MIGRATION-PATH] .venv がリンクです。移動しません。' }
Get-Command git -ErrorAction Stop | Out-Null
$uv = (Get-Command uv -CommandType Application -ErrorAction Stop).Source
$gitRoot = & git -C $workspace rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0 -or [IO.Path]::GetFullPath([string]$gitRoot) -ine $workspace) {
    throw '[E-MIGRATION-GIT] 対象が Git ルートではありません。'
}
$version = & $python -I -S -B -c 'import sys; print(*sys.version_info[:2],sep=chr(46))'
if ($LASTEXITCODE -ne 0 -or [string]$version -ne '3.11') { throw '[E-MIGRATION-VERSION] 切り替え元は Python 3.11 に限ります。' }

function Get-MigrationProcesses {
    $result = @()
    $escapedEnvironment = [regex]::Escape($environmentPath + '\Scripts\')
    foreach ($process in @(Get-CimInstance Win32_Process)) {
        $executable = [string]$process.ExecutablePath
        $command = [string]$process.CommandLine
        $owned = $executable.StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase) -or $command -match ('(?i)^"?' + $escapedEnvironment + 'pythonw?\.exe"?(\s|$)')
        $role = 'other'
        if ($command -match '(?i)(-m\s+workers\.runner\b|[\\/]workers[\\/]runner\.py\b)') { $role = 'runner' }
        elseif ($command -match '(?i)(-m\s+web_app\.app\b|--post-fixed-comments\b)') { $role = 'application' }
        $ambiguous = -not $owned -and $role -ne 'other'
        # 別の .venv が明示されている接続は、対象ワークスペースのプロセスと扱わない。
        if ($ambiguous -and ($executable -match '(?i)[\\/]\.venv[\\/]Scripts[\\/]' -or $command -match '(?i)^"?[A-Z]:[\\/].*[\\/]\.venv[\\/]Scripts[\\/]pythonw?\.exe')) { $ambiguous = $false }
        $created = $null
        if ($null -ne $process.CreationDate) { $created = $process.CreationDate.ToUniversalTime().ToString('o') }
        $consoleHost = $executable -ieq (Join-Path $env:SystemRoot 'System32\conhost.exe')
        $result += [pscustomobject]@{ pid = [int]$process.ProcessId; name = [string]$process.Name; parent = [int]$process.ParentProcessId; created_at = $created; workspace = [bool]$owned; role = $role; ambiguous = [bool]$ambiguous; console_host = [bool]$consoleHost }
    }
    # Windows の venv ランチャーは別の base Python を子として起動する。
    # 同じ runner の直接の子で、作成順序も一致する Python だけ所属を引き継ぐ。
    $progress = $true
    while ($progress) {
        $progress = $false
        foreach ($child in $result) {
            if ($child.workspace -or $child.role -ne 'runner' -or $child.name -notmatch '^(?i)pythonw?\.exe$' -or -not $child.created_at) { continue }
            $parents = @($result | Where-Object { $_.pid -eq $child.parent -and $_.workspace -and $_.role -eq 'runner' -and $_.created_at })
            if ($parents.Count -eq 1 -and [DateTime]::Parse($child.created_at).ToUniversalTime() -ge [DateTime]::Parse($parents[0].created_at).ToUniversalTime()) {
                $child.workspace = $true
                $child.ambiguous = $false
                $progress = $true
            }
        }
    }
    return $result
}

function Get-MigrationState {
    param([string]$Interpreter)
    $processes = @(Get-MigrationProcesses)
    $serialized = ConvertTo-Json -InputObject $processes -Compress -Depth 4
    $raw = $serialized | & $Interpreter -I -S -B $helper probe --root $workspace
    if ($LASTEXITCODE -ne 0) { throw '[E-MIGRATION-CHECK] DB とジョブの読み取り検査に失敗しました。切り替えません。' }
    $state = ([string]$raw | ConvertFrom-Json)
    if (-not $state.ok) { throw '[E-MIGRATION-CHECK] 事前検査を通過していません。' }
    $tasks = @(Get-ScheduledTask | Where-Object {
        if ($_.State -eq 'Disabled') { return $false }
        foreach ($action in $_.Actions) {
            if (([string]$action.Execute).StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase) -or ([string]$action.Arguments).IndexOf($workspace, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
        }
        return $false
    })
    return [pscustomobject]@{ Check = $state; Processes = $processes; EnabledTasks = $tasks.Count }
}

function Assert-MigrationReady {
    param($State)
    $check = $State.Check
    Write-Host ('DB={0}, 自動運用ON={1}, queued={2}, 稼働running={3}, 旧running={4}, 判定不能running={5}, 未生成metadata={6}' -f $check.databases, $check.autopilot_enabled, $check.queued, $check.running_active, $check.running_historical, $check.running_ambiguous, $check.missing_metadata)
    if ($check.autopilot_enabled -ne 0 -or $check.queued -ne 0 -or $check.running_active -ne 0 -or $check.running_ambiguous -ne 0) {
        throw '[E-MIGRATION-BUSY] 自動運用・未処理ジョブ・実行中または判定不能ジョブがあります。元の記録を変更せず停止します。'
    }
    if ($State.EnabledTasks -ne 0) { throw '[E-MIGRATION-TASK] 対象ワークスペースを起動する有効な OS タスクがあります。自動で無効化せず停止します。' }
    $blockers = @($State.Processes | Where-Object { $_.ambiguous -or ($_.workspace -and $_.role -ne 'runner') })
    if ($blockers.Count -gt 0) {
        foreach ($blocker in $blockers) { Write-Host ('停止理由のプロセス: PID={0}, 実行名={1}, 種別={2}, 対象所属={3}' -f $blocker.pid, $blocker.name, $blocker.role, $blocker.workspace) }
        throw '[E-MIGRATION-PROCESS] Web UI・他の対象プロセスまたは所属不明の処理があります。引数や秘密値は表示せず停止します。'
    }
    $runners = @($State.Processes | Where-Object { $_.workspace -and $_.role -eq 'runner' })
    if (@($runners | Where-Object { -not $_.created_at }).Count -ne 0) { throw '[E-MIGRATION-PROCESS] runner の作成日時を確認できません。' }
    foreach ($runner in $runners) {
        $children = @($State.Processes | Where-Object {
            $_.parent -eq $runner.pid -and -not ($_.workspace -and $_.role -eq 'runner') -and -not (
                $_.console_host -and $_.created_at -and [DateTime]::Parse($_.created_at).ToUniversalTime() -ge [DateTime]::Parse($runner.created_at).ToUniversalTime()
            )
        })
        if ($children.Count -ne 0) { throw '[E-MIGRATION-PROCESS] idle runner と確認できない子プロセスがあります。' }
    }
}

function Get-RunnerStopOrder {
    param([object[]]$Runners)
    $pendingRunners = @($Runners)
    $ordered = @()
    while ($pendingRunners.Count -gt 0) {
        $leaves = @($pendingRunners | Where-Object {
            $candidatePid = $_.pid
            @($pendingRunners | Where-Object { $_.parent -eq $candidatePid }).Count -eq 0
        })
        if ($leaves.Count -eq 0) { throw '[E-MIGRATION-PROCESS] runner の親子関係が循環しています。停止しません。' }
        $ordered += $leaves
        $leafPids = @($leaves | ForEach-Object { $_.pid })
        $pendingRunners = @($pendingRunners | Where-Object { $_.pid -notin $leafPids })
    }
    return $ordered
}

$initial = Get-MigrationState -Interpreter $python
Assert-MigrationReady -State $initial
if (-not $Apply) {
    Write-Host '読み取り確認のみです。プロセス・DB・仮想環境・退避先は変更していません。'
    Write-Host '切り替える場合だけ -Apply を明示してください。生成・レンダーの実サンプル受入は別途必要です。'
    return
}

$token = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N')
$backup = Join-Path $backupBase $token
$partial = Join-Path $temporaryRoot ('failed-environment-' + $token)
$moved = $false
$savedVariables = @{}
foreach ($name in @('PYTHONIOENCODING', 'PYTHONDONTWRITEBYTECODE', 'UV_PROJECT_ENVIRONMENT', 'UV_PYTHON_DOWNLOADS')) {
    $savedVariables[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:UV_PROJECT_ENVIRONMENT = $environmentPath
    $env:UV_PYTHON_DOWNLOADS = 'never'
    Write-Host '切り替え前の DB・鍵・認証ファイル・Git 差分をリポジトリ外へ退避します。'
    $backupReport = & $python -I -S -B $helper backup --root $workspace --destination $backup --timeout-seconds $OperationTimeoutSeconds --apply
    if ($LASTEXITCODE -ne 0) { throw '[E-MIGRATION-BACKUP] 退避に失敗しました。仮想環境は移動していません。' }
    Write-Host '旧 3.11 の隔離全テストとオフラインオラクルを実行します。'
    $oldTests = & $python -I -S -B $helper tests --root $workspace --destination $backup --label python311 --timeout-seconds $OperationTimeoutSeconds --apply
    if ($LASTEXITCODE -ne 0) { throw '[E-MIGRATION-BASELINE] 切り替え前の検証に失敗しました。環境は切り替えません。' }
    # 長い検証の間にジョブが増えていないことを、停止直前に再確認する。
    $ready = Get-MigrationState -Interpreter $python
    Assert-MigrationReady -State $ready
    $originalRunners = @($ready.Processes | Where-Object { $_.workspace -and $_.role -eq 'runner' })
    $runners = @(Get-RunnerStopOrder -Runners $originalRunners)
    Write-Host '対象ワークスペースの idle runner だけを作成日時と照合して停止し、Python 環境を切り替えます。'
    foreach ($runner in $runners) {
        $immediate = Get-MigrationState -Interpreter $python
        Assert-MigrationReady -State $immediate
        $same = @($immediate.Processes | Where-Object { $_.pid -eq $runner.pid })
        if ($same.Count -eq 0) { Write-Host ('runner PID {0} は既に終了しています。' -f $runner.pid); continue }
        if ($same[0].created_at -ne $runner.created_at -or -not $same[0].workspace -or $same[0].role -ne 'runner') { throw '[E-MIGRATION-PID] PID の所有者が変わりました。停止しません。' }
        $live = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $runner.pid)
        if ($null -ne $live) {
            if ($live.CreationDate.ToUniversalTime().ToString('o') -ne $runner.created_at) { throw '[E-MIGRATION-PID] 作成日時が変わりました。停止しません。' }
            $native = Get-Process -Id $runner.pid -ErrorAction Stop
            try {
                $handle = $native.Handle
                if ($native.StartTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.ffffff') -ne $live.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.ffffff')) { throw '[E-MIGRATION-PID] 実プロセスの作成日時が一致しません。停止しません。' }
                $native.Kill()
                if (-not $native.WaitForExit($StopTimeoutSeconds * 1000)) { throw '[E-MIGRATION-PROCESS] runner の終了待機が上限を超えました。環境を移動しません。' }
            } finally { $native.Dispose() }
        }
        $afterStop = Get-MigrationState -Interpreter $python
        Assert-MigrationReady -State $afterStop
        foreach ($remainingRunner in @($afterStop.Processes | Where-Object { $_.workspace -and $_.role -eq 'runner' })) {
            $original = @($originalRunners | Where-Object { $_.pid -eq $remainingRunner.pid -and $_.created_at -eq $remainingRunner.created_at })
            if ($original.Count -ne 1) { throw '[E-MIGRATION-PROCESS] 停止中に runner が再生成されました。新しいプロセスには触れず、環境の移動を中止します。' }
        }
    }
    $stopped = Get-MigrationState -Interpreter $python
    Assert-MigrationReady -State $stopped
    if (@($stopped.Processes | Where-Object { $_.workspace }).Count -ne 0) { throw '[E-MIGRATION-PROCESS] 対象プロセスが残っています。環境を移動しません。' }
    # 停止後の状態をもう一度退避する。先の退避を上書きしない。
    $finalBackup = Join-Path $backup 'before-environment-move'
    $finalReport = & $python -I -S -B $helper backup --root $workspace --destination $finalBackup --timeout-seconds $OperationTimeoutSeconds --apply
    if ($LASTEXITCODE -ne 0) { throw '[E-MIGRATION-BACKUP] 停止後の再退避に失敗しました。環境を移動しません。' }
    Move-Item -LiteralPath $environmentPath -Destination $oldEnvironment
    $moved = $true
    $preservedPython = Join-Path $oldEnvironment 'Scripts\python.exe'
    $syncReport = & $preservedPython -I -S -B $helper sync --root $workspace --destination $backup --uv $uv --timeout-seconds $OperationTimeoutSeconds --apply
    if ($LASTEXITCODE -ne 0) { throw '[E-MIGRATION-UV] uv sync が失敗しました。' }
    $newVersion = & $python -I -S -B -c 'import sys; print(*sys.version_info[:2],sep=chr(46))'
    if ($LASTEXITCODE -ne 0 -or [string]$newVersion -ne '3.12') { throw '[E-MIGRATION-VERSION] 新環境が Python 3.12 ではありません。' }
    $newTests = & $python -I -S -B $helper tests --root $workspace --destination $backup --label python312 --timeout-seconds $OperationTimeoutSeconds --apply
    if ($LASTEXITCODE -ne 0) { throw '[E-MIGRATION-TEST] 新環境のテスト・件数照合・オラクルが不合格です。' }
    Write-Host ('Python 3.12 への切り替えと隔離検証が成功しました。退避先: ' + $backup)
    Write-Host '.venv-311-backup は保持しています。runner は停止状態です。実生成・実レンダーのサンプル受入は未実行で、移行全体の完了ではありません。'
} catch {
    if (Test-Path -LiteralPath $backup -PathType Container) {
        $_ | Out-String | Add-Content -LiteralPath (Join-Path $backup 'app_debug_migration.log') -Encoding UTF8
    }
    if ($moved) {
        if (Test-Path -LiteralPath $environmentPath) {
            New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
            # 事前に検証した専用 temp の配下へだけ移す。部分環境を削除しない。
            if (-not ([IO.Path]::GetFullPath($partial)).StartsWith($temporaryRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '[E-MIGRATION-ROLLBACK] 部分環境の保管先が不正です。旧環境は .venv-311-backup に保持しています。' }
            Move-Item -LiteralPath $environmentPath -Destination $partial
        }
        Move-Item -LiteralPath $oldEnvironment -Destination $environmentPath
        Write-Host '失敗した部分環境を保管し、旧 .venv を元の場所へ戻しました。停止済み runner は再起動していません。'
    }
    throw '[E-MIGRATION-FAILED] 切り替えを完了できませんでした。退避先のデバッグログと .venv/.venv-311-backup の実体を確認してください。'
} finally {
    foreach ($name in $savedVariables.Keys) { [Environment]::SetEnvironmentVariable($name, $savedVariables[$name], 'Process') }
}
