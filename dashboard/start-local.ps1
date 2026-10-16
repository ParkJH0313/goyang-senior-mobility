param([ValidateSet('gemini','openai')][string]$Provider = 'gemini')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$nodeCommand = Get-Command node -ErrorAction Stop
function Read-SessionKey([string]$Name, [string]$Prompt) {
    if ([Environment]::GetEnvironmentVariable($Name, 'Process')) { return }
    $secretValue = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secretValue)
    try {
        [Environment]::SetEnvironmentVariable($Name, [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer), 'Process')
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        $secretValue.Dispose()
    }
}
$env:AI_PROVIDER = $Provider
Read-SessionKey 'KAKAO_JAVASCRIPT_KEY' 'Kakao JavaScript key (Enter to skip map)'
Read-SessionKey 'KAKAO_REST_API_KEY' 'Kakao REST API key (Enter to skip distances)'
if ($Provider -eq 'gemini') { Read-SessionKey 'GEMINI_API_KEY' 'Gemini API key (Enter to preview without AI)' }
else { Read-SessionKey 'OPENAI_API_KEY' 'OpenAI API key (Enter to preview without AI)' }
$env:PORT = '8080'
$env:HOST = '127.0.0.1'
$env:APP_ORIGIN = 'http://localhost:8080'
& $nodeCommand.Source 'server.cjs'
