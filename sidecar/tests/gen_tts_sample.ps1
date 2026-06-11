# Generate a spoken WAV of the fixture transcript using Windows SAPI TTS.
# Lets the ASR word-count gate run with known ground-truth text, no human mic.
param(
    [string]$TextFile = "$PSScriptRoot\fixtures\sample_transcript.txt",
    [string]$OutFile = "$PSScriptRoot\fixtures\tts_sample.wav"
)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 1
$synth.SetOutputToWaveFile($OutFile)
$text = Get-Content $TextFile -Raw
$synth.Speak($text)
$synth.Dispose()
$words = ($text -split '\s+' | Where-Object { $_ }).Count
Write-Output "wrote $OutFile ($words ground-truth words)"
