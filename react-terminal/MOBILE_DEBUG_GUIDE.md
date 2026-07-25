# Mobile View Debug Guide

## Issues Fixed ✅

1. **Vite config** - Updated to explicitly bind to `0.0.0.0` instead of `true`
2. **DevTunnel support** - Added `strictPort: false` and `allowedHosts: ['*']`
3. **Browser caching** - Added `Cache-Control: no-store` headers
4. **Responsive CSS** - Added media queries for screens ≤767px

## How to Test Mobile View

### Option 1: Using DevTunnel on Your Phone (Recommended)
```powershell
# Terminal 1: Start your backend (if needed)
cd c:\Users\TOSHIBA\Desktop\Finwise

# Terminal 2: Start React dev server
cd react-terminal
npm run dev

# Terminal 3: Create DevTunnel
devtunnel host -p 58021 --allow-anonymous
# Copy the URL shown and open on your phone
```

### Option 2: Using Chrome DevTools Emulation
1. Open http://localhost:58021 on your computer
2. Press `F12` to open DevTools
3. Press `Ctrl+Shift+M` (or click device icon) to toggle mobile emulation
4. Select a mobile device (e.g., iPhone 12)
5. Hard refresh: `Ctrl+Shift+R` to clear cache

### Option 3: Local Network Testing
1. Find your computer's IP: `ipconfig` (look for IPv4 address like 192.168.x.x)
2. On phone connected to same WiFi, visit: `http://<YOUR_IP>:58021`
3. Hard refresh if needed

## If Mobile View Still Doesn't Appear

### Step 1: Clear Browser Cache
- **Chrome**: Press `Ctrl+Shift+Delete` → Select "All time" → Clear data
- **Safari iOS**: Settings → Safari → Clear History and Website Data
- **Firefox**: Press `Ctrl+H` → Clear Recent History → Select "All"

### Step 2: Check DevTools Inspector
1. On your phone (or in desktop DevTools mobile view):
2. Open DevTools → Check Console for errors
3. Look for CORS errors or failed requests

### Step 3: Verify DevTunnel Connection
```powershell
# Check if Vite is serving on all interfaces
netstat -ano | findstr "58021"
# Should show LISTENING on 0.0.0.0 or your IP
```

### Step 4: Check Viewport Meta Tag
- Open DevTools → Inspector
- Look for the `<meta name="viewport">` tag
- It should say: `width=device-width, initial-scale=1.0, viewport-fit=cover`

## Browser User Agent Check
The mobile view should detect your device based on:
- **Viewport width** (≤767px triggers mobile styles)
- **Device detection** via user agent (automatic)

## Testing Checklist
- [ ] Hard refresh (Ctrl+Shift+R or Cmd+Shift+R)
- [ ] Browser cache cleared
- [ ] DevTools shows mobile viewport ≤430px width
- [ ] No CORS errors in console
- [ ] API/WebSocket calls working
- [ ] Bottom navigation visible
- [ ] Touch interactions working (on phone)

## Vite Dev Server Commands

```bash
# Start dev server (should bind to 0.0.0.0:58021)
npm run dev

# If you want to specify host explicitly:
vite --host 0.0.0.0 --port 58021

# Build for production (minified, optimized)
npm run build

# Preview production build
npm run preview
```

## DevTunnel Setup
```powershell
# If devtunnel isn't installed
dotnet tool install -g Microsoft.DevTunnels.CLI

# Start tunnel
devtunnel host -p 58021 --allow-anonymous

# Output will show:
# Tunnel host started. Press Ctrl + C to exit.
# Ready to receive connections at: https://<tunnel-name>.devtunnels.ms
```

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| Page loads but no mobile styles | Hard refresh & check viewport meta tag |
| DevTunnel shows 404 | Ensure React dev server is running |
| API calls fail on phone | Check CORS headers, verify backend URL |
| Bottom nav not visible | Check CSS media query is loading |
| Responsive but desktop view showing | Check max-width constraint in CSS |
| DevTunnel connection drops | Restart tunnel and refresh page |

## Gmail OAuth For Password Reset

Password reset email delivery depends on a valid Gmail OAuth token. If the app shows `Gmail OAuth token is missing on this server`, the sender has not been authorized yet or the token file is gone.

### What The App Expects

- `GMAIL_ADDRESS` must be set in `.env`
- `credentials.json` must exist in the project root
- `token.json` must exist in the project root after a successful authorization
- `OAUTH_REDIRECT_URI` should match the local app URL, for example `http://localhost:8051`

### How To Recreate The Token

1. Start the Finwise app on the same port used by `OAUTH_REDIRECT_URI`.
2. Open the desktop auth flow, not the password reset flow.
3. Trigger a Gmail-backed action that allows interactive authorization, such as account verification or registration.
4. Click the `Authorize Gmail Access` link if the app shows one.
5. Finish the Google consent screen and return to the app.
6. Confirm that `token.json` appears in `C:\Users\User\Desktop\Finwise`.

### Important Behavior

- Password reset itself will not start an interactive Gmail OAuth flow.
- If the sender token is missing or expired, the reset request will fail immediately with a clear message.
- If the token exists but is invalid, you may need to reconnect the Gmail account from the desktop flow again.

## CSS Media Query Reference
- Desktop: `> 767px` → Desktop layout
- Tablet: `481px - 767px` → Tablet layout  
- Mobile: `≤ 480px` → Mobile layout (full screen)

Current mobile CSS uses `min(100%, 430px)` which means:
- On phone (≤430px width): Full width
- On tablet (>430px): Centered 430px container

