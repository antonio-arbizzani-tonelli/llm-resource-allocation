param(
    [string]$OutputPath = "results/nightly_campaign",
    [ValidateSet("gurobi", "highs")][string]$Backend,
    [string]$WslDistribution = "Ubuntu",
    [switch]$Resume
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = "python" }
if (-not [System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath = Join-Path $projectRoot $OutputPath }
$campaignArguments = @((Join-Path $PSScriptRoot "run_nightly_campaign.py"), "--output", $OutputPath, "--wsl", $WslDistribution)
if ($Resume) {
    $campaignArguments[0] = Join-Path $OutputPath "snapshot/scripts/run_nightly_campaign.py"
    $campaignArguments += @("--resume", "--config", (Join-Path $OutputPath "snapshot/configs/nightly_campaign.json"))
}
if ($Backend) { $campaignArguments += @("--backend", $Backend) }
# A thread-scoped request prevents automatic sleep during this process only.
# It leaves screen-off, lid-close actions and the global power plan unchanged.
if (-not ("AllocationCampaignPower" -as [type])) {
    Add-Type @'
using System.Runtime.InteropServices;
public static class AllocationCampaignPower {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint flags);
}
'@
}
$request = [AllocationCampaignPower]::SetThreadExecutionState([uint32]2147483649)
if ($request -eq 0) { throw "Windows rejected the temporary automatic-sleep prevention request." }
$campaignExitCode = 1
try {
    & $pythonPath @campaignArguments
    $campaignExitCode = $LASTEXITCODE
} finally {
    [void][AllocationCampaignPower]::SetThreadExecutionState([uint32]2147483648)
}
exit $campaignExitCode
