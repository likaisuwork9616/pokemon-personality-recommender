#!/usr/bin/env pwsh
#requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [uri]$BaseUrl,

    [ValidateRange(4, 20)]
    [int]$RateLimitAttempts = 6,

    [ValidateRange(1, 120)]
    [int]$TimeoutSeconds = 30,

    [switch]$AllowNonQuickTunnelHost
)

$ErrorActionPreference = "Stop"

if ($BaseUrl.Scheme -ne "https") {
    throw "BaseUrl must use HTTPS."
}
if ($BaseUrl.UserInfo -or $BaseUrl.Query -or $BaseUrl.Fragment) {
    throw "BaseUrl must not contain credentials, a query, or a fragment."
}
if ($BaseUrl.AbsolutePath -notin @("", "/")) {
    throw "BaseUrl must be an origin without a path."
}
if (
    -not $AllowNonQuickTunnelHost -and
    -not $BaseUrl.DnsSafeHost.EndsWith(".trycloudflare.com", [StringComparison]::OrdinalIgnoreCase)
) {
    throw "BaseUrl must be a trycloudflare.com Quick Tunnel URL unless -AllowNonQuickTunnelHost is set."
}

$origin = $BaseUrl.GetLeftPart([UriPartial]::Authority)
$recommendationBody = @{
    text = "我冷靜可靠，喜歡幫助朋友，也願意耐心完成承諾。"
    generate_explanation = $false
} | ConvertTo-Json -Compress

function Invoke-TunnelRequest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [ValidateSet("GET", "POST")]
        [string]$Method = "GET",

        [hashtable]$Headers,

        [AllowNull()]
        [string]$Body = $null
    )

    $request = @{
        Uri = "$origin/$($Path.TrimStart('/'))"
        Method = $Method
        TimeoutSec = $TimeoutSeconds
        SkipHttpErrorCheck = $true
        ErrorAction = "Stop"
        UserAgent = "pokemon-quick-tunnel-smoke/1"
    }
    if ($null -ne $Headers) {
        $request.Headers = $Headers
    }
    if ($null -ne $Body) {
        $request.Body = $Body
        $request.ContentType = "application/json; charset=utf-8"
    }
    Invoke-WebRequest @request
}

function Assert-Status {
    param(
        [Parameter(Mandatory = $true)]
        $Response,

        [Parameter(Mandatory = $true)]
        [int]$Expected,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if ([int]$Response.StatusCode -ne $Expected) {
        throw "$Label returned HTTP $($Response.StatusCode); expected $Expected."
    }
    Write-Host "[ok] $Label -> HTTP $Expected"
}

function ConvertFrom-ResponseJson {
    param(
        [Parameter(Mandatory = $true)]
        $Response,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    try {
        $Response.Content | ConvertFrom-Json -Depth 32
    }
    catch {
        throw "$Label did not return valid JSON: $($_.Exception.Message)"
    }
}

$liveResponse = Invoke-TunnelRequest -Path "/health/live"
Assert-Status -Response $liveResponse -Expected 200 -Label "liveness"
$live = ConvertFrom-ResponseJson -Response $liveResponse -Label "liveness"
if ($live.status -ne "ok") {
    throw "Liveness response contract changed."
}

$readyResponse = Invoke-TunnelRequest -Path "/health/ready"
Assert-Status -Response $readyResponse -Expected 200 -Label "readiness"
$ready = ConvertFrom-ResponseJson -Response $readyResponse -Label "readiness"
if ($ready.status -ne "ready") {
    throw "Readiness response contract changed."
}

$rootResponse = Invoke-TunnelRequest -Path "/"
Assert-Status -Response $rootResponse -Expected 200 -Label "root page"
if (
    $rootResponse.Content -notmatch [regex]::Escape("本站為非官方、非商業") -or
    $rootResponse.Content -notmatch [regex]::Escape("The Pokémon Company")
) {
    throw "Root page is missing the public rights disclaimer."
}
Write-Host "[ok] root page includes the noncommercial rights disclaimer"

$metricsResponse = Invoke-TunnelRequest -Path "/metrics"
Assert-Status -Response $metricsResponse -Expected 404 -Label "public metrics boundary"

$oversizeBody = @{
    text = ("x" * 20KB)
    generate_explanation = $false
} | ConvertTo-Json -Compress
$oversizeResponse = Invoke-TunnelRequest `
    -Path "/api/v1/recommendations" `
    -Method "POST" `
    -Body $oversizeBody
Assert-Status -Response $oversizeResponse -Expected 413 -Label "Caddy 16 KB request-body boundary"

$fallbackBody = @{
    text = "我慢熟但重視承諾，遇到朋友需要幫忙時會耐心陪伴。"
    generate_explanation = $true
} | ConvertTo-Json -Compress
$fallbackResponse = Invoke-TunnelRequest `
    -Path "/api/v1/recommendations" `
    -Method "POST" `
    -Body $fallbackBody
Assert-Status -Response $fallbackResponse -Expected 200 -Label "recommendation with explanation"
$recommendation = ConvertFrom-ResponseJson -Response $fallbackResponse -Label "recommendation"
if (@($recommendation.results).Count -ne 3) {
    throw "Recommendation response did not contain exactly three results."
}
$explanation = $recommendation.results[0].explanation
if (
    $null -eq $explanation -or
    $explanation.provider -ne "local" -or
    -not [bool]$explanation.used_fallback -or
    -not [bool]$explanation.grounded
) {
    throw "Recommendation did not use the grounded local fallback while provider keys were blank."
}
Write-Host "[ok] recommendation used the grounded local fallback"

$imageUrl = [string]$recommendation.results[0].pokemon.image_url
if ([string]::IsNullOrWhiteSpace($imageUrl)) {
    throw "Top recommendation did not include an image URL."
}
$imageUri = [uri]$imageUrl
if ($imageUri.Scheme -ne "https") {
    throw "Top recommendation image URL is not HTTPS."
}
$imageResponse = Invoke-WebRequest `
    -Uri $imageUri `
    -Method "GET" `
    -Headers @{ Range = "bytes=0-1023" } `
    -TimeoutSec $TimeoutSeconds `
    -SkipHttpErrorCheck `
    -UserAgent "pokemon-quick-tunnel-smoke/1"
if ([int]$imageResponse.StatusCode -notin @(200, 206)) {
    throw "Top recommendation image returned HTTP $($imageResponse.StatusCode); expected 200 or 206."
}
$imageContentType = [string]$imageResponse.Headers["Content-Type"]
if (-not $imageContentType.StartsWith("image/", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Top recommendation image returned unexpected Content-Type '$imageContentType'."
}
Write-Host "[ok] top recommendation image is retrievable over HTTPS"

$rateLimited = $false
for ($attempt = 1; $attempt -le $RateLimitAttempts; $attempt++) {
    $spoofedAddress = "198.51.100.$attempt"
    $response = Invoke-TunnelRequest `
        -Path "/api/v1/recommendations" `
        -Method "POST" `
        -Headers @{
            "X-Forwarded-For" = $spoofedAddress
            "X-Real-IP" = $spoofedAddress
        } `
        -Body $recommendationBody

    if ([int]$response.StatusCode -eq 429) {
        $payload = ConvertFrom-ResponseJson -Response $response -Label "rate-limit response"
        if ($payload.detail.code -ne "recommendation_rate_limited") {
            throw "HTTP 429 did not come from the application recommendation guard."
        }
        if (-not $response.Headers["Retry-After"]) {
            throw "Rate-limit response is missing Retry-After."
        }
        $rateLimited = $true
        Write-Host "[ok] changing forwarded-address headers did not bypass the client rate limit"
        break
    }
    if ([int]$response.StatusCode -ne 200) {
        throw "Rate-limit attempt $attempt returned HTTP $($response.StatusCode); expected 200 or 429."
    }
}
if (-not $rateLimited) {
    throw "No rate-limit response was observed after $RateLimitAttempts spoof attempts."
}

Write-Host "Quick Tunnel smoke test passed for $origin"
