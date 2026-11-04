param(
    [Parameter(Mandatory=$true)][string]$InputDocx,
    [Parameter(Mandatory=$true)][string]$OutputPdf
)
$ErrorActionPreference = 'Stop'
$inputFile = (Resolve-Path -LiteralPath $InputDocx).Path
$outputFile = [System.IO.Path]::GetFullPath($OutputPdf)
$wordApp = New-Object -ComObject Word.Application
$reportDocument = $null
try {
    $wordApp.Visible = $false
    $wordApp.DisplayAlerts = 0
    $reportDocument = $wordApp.Documents.Open($inputFile, $false, $true)
    $reportDocument.Fields.Update() | Out-Null
    $reportDocument.Repaginate()
    $reportDocument.ExportAsFixedFormat($outputFile, 17)
    Get-Item -LiteralPath $outputFile | Select-Object FullName, Length
} finally {
    if ($null -ne $reportDocument) { $reportDocument.Close(0) }
    $wordApp.Quit()
}
