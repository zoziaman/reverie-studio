
try {
    $r = Invoke-WebRequest -Uri 'http://localhost:9880' -TimeoutSec 5 -UseBasicParsing
    Write-Output ('Status: ' + $r.StatusCode)
} catch {
    Write-Output ('Error: ' + $_.Exception.Message)
}

Write-Output '--- TTS endpoint test ---'
try {
    $body = '{}'
    $r2 = Invoke-WebRequest -Uri 'http://localhost:9880/tts' -Method POST -ContentType 'application/json' -Body $body -TimeoutSec 5 -UseBasicParsing
    Write-Output ('TTS Status: ' + $r2.StatusCode)
} catch {
    Write-Output ('TTS Error: ' + $_.Exception.Message)
}
