$ErrorActionPreference = 'Stop'
$repo = Resolve-Path (Join-Path $PSScriptRoot '../..')
docker build --target tests --file "$repo/training/Dockerfile" --tag kpdl-ml-tests "$repo"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
docker run --rm --network none kpdl-ml-tests
exit $LASTEXITCODE
