param(
    [ValidateSet('Unit', 'Integration', 'All')]
    [string]$Mode = 'All',
    [ValidatePattern('^kpdl-api-tests-[a-z0-9][a-z0-9-]*$')]
    [string]$ProjectName = "kpdl-api-tests-$PID",
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'
$composeFile = Join-Path $PSScriptRoot 'compose.yml'
$composeArgs = @('compose', '--file', $composeFile, '--project-name', $ProjectName)
$testExit = 1
try {
    # Build sequentially to fit developer laptops; Docker reuses service layers.
    $images = if ($Mode -eq 'All') { @('analysis', 'clustering', 'prediction', 'api', 'tests') } else { @('tests') }
    foreach ($image in $images) {
        & docker @composeArgs build $image
        if ($LASTEXITCODE -ne 0) { throw "Cannot build $image" }
    }
    if ($Mode -eq 'All') {
        & docker @composeArgs up --no-build --abort-on-container-exit --exit-code-from tests
    } else {
        $marker = 'not integration and not keycloak'
        if ($Mode -eq 'Integration') {
            & docker @composeArgs up --detach --wait mart-db warehouse-db
            if ($LASTEXITCODE -ne 0) { throw 'Test PostgreSQL is not ready' }
            $marker = 'not keycloak'
        }
        & docker @composeArgs run --rm --no-deps tests python -m pytest -c pytest.ini tests -q -p no:cacheprovider -m $marker
    }
    $testExit = $LASTEXITCODE
} finally {
    if (-not $Keep) {
        # The validated project prefix and standalone YAML only own disposable test resources.
        & docker @composeArgs down --volumes --remove-orphans
    } else {
        Write-Host "Test resources kept in $ProjectName. Cleanup: docker compose -f `"$composeFile`" -p $ProjectName down --volumes"
    }
}
exit $testExit
