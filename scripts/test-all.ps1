# Module 14 regression suite (Windows PowerShell wrapper). Arguments are passed through:
#   .\scripts\test-all.ps1                    # this machine
#   .\scripts\test-all.ps1 --backend-docker   # backend in the Linux test image (PostgreSQL tests run)
node "$PSScriptRoot\test-all.mjs" @args
exit $LASTEXITCODE
