// Master Google Sheet ID: https://docs.google.com/spreadsheets/d/12xEfxLTOw8D4K8Qi_kj0RWPl12hID6x5HZpvU_AsTLE/edit
const SPREADSHEET_ID = "12xEfxLTOw8D4K8Qi_kj0RWPl12hID6x5HZpvU_AsTLE";

// Master Google Drive Folder ID: https://drive.google.com/drive/folders/16-ifHQQPv2vZ_eTVZvx8CiGilVy9dQ8r
const ROOT_FOLDER_ID = "16-ifHQQPv2vZ_eTVZvx8CiGilVy9dQ8r";

function getSpreadsheet() {
  if (SPREADSHEET_ID && SPREADSHEET_ID.trim() !== "") {
    try {
      return SpreadsheetApp.openById(SPREADSHEET_ID.trim());
    } catch (e) {}
  }
  return SpreadsheetApp.getActiveSpreadsheet();
}

// Constant-time string comparison to prevent timing attacks
function secureCompare(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

function hashToken(token) {
  const bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, token, Utilities.Charset.UTF_8);
  return bytes.map(b => (b < 0 ? b + 256 : b).toString(16).padStart(2, '0')).join('');
}

function doGet(e) {
  return successResponse({ status: "ok", service: "backup-broker" });
}

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);
    const action = payload.action;

    if (action === "health") {
      return successResponse({ status: "ok", service: "backup-broker" });
    }
    
    // Enroll doesn't need a pre-existing token, but uses an enrollment code
    if (action === "enroll") {
      return handleEnroll(payload);
    }

    // All other actions require a valid token
    const token = payload.token;
    if (!token) return errorResponse("Missing token", 401);

    const pcData = verifyToken(token);
    if (!pcData) {
      logAudit("UNKNOWN", "AUTH_FAILURE", "Invalid token attempt");
      return errorResponse("Unauthorized", 401);
    }

    if (action === "verify") {
      return successResponse({ pc_id: pcData.pcId, offset_minutes: pcData.offset });
    } else if (action === "request_upload") {
      return handleRequestUpload(pcData, payload);
    } else if (action === "report_status") {
      return handleReportStatus(pcData, payload);
    } else {
      return errorResponse("Unknown action", 400);
    }

  } catch (err) {
    return errorResponse("Internal server error: " + err.message, 500);
  }
}

function handleEnroll(payload) {
  const enrollCode = String(payload.enroll_code || "").trim();
  const pcId = String(payload.pc_id || "").trim();
  const customerSlug = String(payload.customer_slug || "").trim();
  const providedToken = String(payload.token || "").trim();
  
  if (!enrollCode || !pcId || !providedToken || !customerSlug) {
    return errorResponse("Missing fields", 400);
  }

  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    return errorResponse("System busy", 429);
  }

  try {
    const ss = getSpreadsheet();
    const configSheet = ss.getSheetByName("Config");
    const tokensSheet = ss.getSheetByName("Tokens");
    
    // Verify enrollment code and slug from config
    const configData = configSheet.getDataRange().getValues();
    let validCode = false;
    for (let i = 1; i < configData.length; i++) {
      const key = String(configData[i][0] || "").trim();
      const storedCode = String(configData[i][1] || "").trim();
      if (key === "ENROLL_CODE" && storedCode && secureCompare(storedCode, enrollCode)) {
        const expectedSlug = String(configData[i][2] || "").trim();
        // Slug must be present and match strictly (case-insensitive)
        if (expectedSlug && secureCompare(expectedSlug.toLowerCase(), customerSlug.toLowerCase())) {
          validCode = true;
          break;
        }
      }
    }
    if (!validCode) {
      logAudit(pcId, "ENROLL_FAILURE", "Invalid enrollment code or slug mismatch");
      return errorResponse("Unauthorized", 401);
    }
    
    // Check if PC already enrolled -> allow re-enrollment if valid ENROLL_CODE was provided
    let existingRowIndex = -1;
    const tokenData = tokensSheet.getDataRange().getValues();
    for (let i = 1; i < tokenData.length; i++) {
      if (tokenData[i][0] === pcId) {
        existingRowIndex = i + 1; // 1-indexed sheet row
        break;
      }
    }

    const tokenHash = hashToken(providedToken);
    const offset = Math.floor(Math.random() * 240); // 0 to 4 hours stagger offset
    const timestamp = new Date().toISOString();

    if (existingRowIndex > 0) {
      tokensSheet.getRange(existingRowIndex, 1, 1, 5).setValues([[pcId, customerSlug, tokenHash, offset, timestamp]]);
      logAudit(pcId, "RE_ENROLL_SUCCESS", "PC re-enrolled with updated token");
      return successResponse({ status: "re-enrolled", offset_minutes: offset });
    } else {
      tokensSheet.appendRow([pcId, customerSlug, tokenHash, offset, timestamp]);
      logAudit(pcId, "ENROLL_SUCCESS", "PC enrolled successfully");
      return successResponse({ status: "enrolled", offset_minutes: offset });
    }

  } finally {
    lock.releaseLock();
  }
}

function verifyToken(token) {
  const parts = token.split('.');
  if (parts.length !== 2) return null;
  const pcId = parts[0];
  const tokenHash = hashToken(token);

  const ss = getSpreadsheet();
  const tokensSheet = ss.getSheetByName("Tokens");
  const data = tokensSheet.getDataRange().getValues();

  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === pcId && secureCompare(data[i][2], tokenHash)) {
      return { pcId: pcId, customerSlug: data[i][1], offset: data[i][3] };
    }
  }
  return null;
}

function handleRequestUpload(pcData, payload) {
  let dbName = String(payload.db_name || "").trim();
  const sizeBytes = payload.size_bytes;
  
  if (!dbName || !/^[A-Za-z0-9_][A-Za-z0-9_\-\. ]{0,127}$/.test(dbName)) {
    return errorResponse("Invalid database name", 400);
  }
  dbName = dbName.replace(/\s+/g, "_");
  
  const MAX_BYTES = 100 * 1024 * 1024 * 1024; // 100 GB cap
  if (sizeBytes > MAX_BYTES) {
    return errorResponse("Backup size exceeds cap", 413);
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  
  try {
    const today = new Date().toISOString().split('T')[0];
    const ss = getSpreadsheet();
    const auditSheet = ss.getSheetByName("Audit");
    
    // Check 3 slots/day quota
    const data = auditSheet.getDataRange().getValues();
    let countToday = 0;
    for (let i = data.length - 1; i > 0 && i > data.length - 1000; i--) {
      const row = data[i];
      if (row[1] === pcData.pcId && row[2] === "UPLOAD_REQUEST" && row[3] === dbName) {
        if (String(row[0]).startsWith(today)) countToday++;
      }
    }
    
    if (countToday >= 3) {
      logAudit(pcData.pcId, "RATE_LIMIT_EXCEEDED", `DB: ${dbName}`);
      return errorResponse("Daily upload limit reached for this DB", 429);
    }
    
    const seq = countToday + 1;
    const fileName = `${pcData.pcId}_${dbName}_${today}_${seq}.dbk2`;
    
    // Server-chosen folder: ROOT/CustomerSlug/
    const destFolderId = getOrCreateFolder(ROOT_FOLDER_ID, pcData.customerSlug);
    
    // Create Resumable Upload Session via Drive API (UrlFetchApp)
    const sessionUri = createResumableUpload(destFolderId, fileName, sizeBytes);
    
    logAudit(pcData.pcId, "UPLOAD_REQUEST", dbName);
    return successResponse({ upload_url: sessionUri, file_name: fileName });
  } finally {
    lock.releaseLock();
  }
}

function handleReportStatus(pcData, payload) {
  const ss = getSpreadsheet();
  
  // Use module-specific tab, default to Telemetry
  const tabName = payload.tab_name || "Telemetry";
  let sheet = ss.getSheetByName(tabName);
  if (!sheet) {
    sheet = ss.insertSheet(tabName);
  }
  
  const timestamp = new Date().toISOString();
  
  // If payload contains drives, it's the Server Cleanup module
  if (payload.drives && Array.isArray(payload.drives)) {
    payload.drives.forEach(drive => {
      sheet.appendRow([
        timestamp,
        pcData.pcId,
        pcData.customerSlug,
        drive.letter || "",
        drive.total_gb || 0,
        drive.free_gb || 0,
        drive.percent_free || 0
      ]);
    });
    return successResponse({ status: "recorded", drives_logged: payload.drives.length });
  } else {
    // Default fallback for single-line flat reports
    sheet.appendRow([
      timestamp,
      pcData.pcId,
      pcData.customerSlug,
      payload.status || "UNKNOWN",
      payload.message || "",
      payload.db_name || "",
      payload.bytes || 0
    ]);
    return successResponse({ status: "recorded" });
  }
}

function getOrCreateFolder(parentFolderId, folderName) {
  let parent;
  if (!parentFolderId || String(parentFolderId).trim() === "") {
    parent = DriveApp.getRootFolder();
  } else {
    try {
      parent = DriveApp.getFolderById(String(parentFolderId).trim());
    } catch (e) {
      parent = DriveApp.getRootFolder();
    }
  }
  const folders = parent.getFoldersByName(folderName);
  if (folders.hasNext()) return folders.next().getId();
  return parent.createFolder(folderName).getId();
}

function createResumableUpload(folderId, fileName, sizeBytes) {
  // Drive API v3 - Resumable Upload
  const url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable";
  const token = ScriptApp.getOAuthToken();
  
  const metadata = {
    name: fileName,
    parents: [folderId]
  };
  
  const options = {
    method: "POST",
    headers: {
      "Authorization": "Bearer " + token,
      "Content-Type": "application/json; charset=UTF-8",
      "X-Upload-Content-Type": "application/octet-stream",
      "X-Upload-Content-Length": sizeBytes.toString()
    },
    payload: JSON.stringify(metadata),
    muteHttpExceptions: true
  };
  
  const response = UrlFetchApp.fetch(url, options);
  if (response.getResponseCode() === 200) {
    const headers = response.getHeaders();
    return headers['Location'] || headers['location'];
  } else {
    throw new Error("Failed to create resumable upload: " + response.getContentText());
  }
}

function logAudit(pcId, action, details) {
  const ss = getSpreadsheet();
  let auditSheet = ss.getSheetByName("Audit");
  if (!auditSheet) {
    auditSheet = ss.insertSheet("Audit");
    auditSheet.appendRow(["TIMESTAMP", "PC_ID", "ACTION", "DETAILS"]);
  }
  auditSheet.appendRow([new Date().toISOString(), pcId, action, details]);
}

function successResponse(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}

function errorResponse(msg, code) {
  // Apps Script returns 200 HTTP status always via ContentService. 
  // We communicate the code in the payload.
  return ContentService.createTextOutput(JSON.stringify({ error: msg, code: code })).setMimeType(ContentService.MimeType.JSON);
}

// Scheduled Trigger Function: 8-Day Silence Check
function checkSilenceAlerts() {
  const ss = getSpreadsheet();
  const tokensSheet = ss.getSheetByName("Tokens");
  const auditSheet = ss.getSheetByName("Audit");
  if (!tokensSheet || !auditSheet) return;
  
  const pcs = tokensSheet.getDataRange().getValues().slice(1).map(r => r[0]);
  const auditData = auditSheet.getDataRange().getValues();
  
  const lastSeen = {};
  for (let i = 1; i < auditData.length; i++) {
    lastSeen[auditData[i][1]] = new Date(auditData[i][0]).getTime();
  }
  
  const now = Date.now();
  const EIGHT_DAYS = 8 * 24 * 60 * 60 * 1000;
  
  const silentPcs = [];
  pcs.forEach(pc => {
    if (!lastSeen[pc] || (now - lastSeen[pc] > EIGHT_DAYS)) {
      silentPcs.push(pc);
    }
  });
  
  if (silentPcs.length > 0) {
    MailApp.sendEmail({
      to: Session.getEffectiveUser().getEmail(),
      subject: "ALERT: Backup PCs Offline for > 8 Days",
      body: "The following PCs have not checked in:\n" + silentPcs.join("\n")
    });
  }
}

/**
 * Setup Function: Run this once from the Apps Script editor
 * to automatically build all required tabs and column headers.
 */
function setupSheets() {
  const ss = getSpreadsheet();
  
  const requiredSheets = [
    { name: "Config", headers: ["KEY", "VALUE", "CUSTOMER_SLUG", "STATUS"] },
    { name: "Tokens", headers: ["PC_ID", "CUSTOMER_SLUG", "TOKEN_HASH", "OFFSET_MINUTES", "CREATED_AT"] },
    { name: "Audit", headers: ["TIMESTAMP", "PC_ID", "ACTION", "DETAILS"] },
    { name: "Telemetry", headers: ["TIMESTAMP", "PC_ID", "CUSTOMER_SLUG", "STATUS", "MESSAGE", "DB_NAME", "BYTES"] },
    { name: "Storage Monitor", headers: ["TIMESTAMP", "PC_ID", "CUSTOMER_SLUG", "DRIVE", "TOTAL_GB", "FREE_GB", "PERCENT_FREE"] }
  ];
  
  requiredSheets.forEach(spec => {
    let sheet = ss.getSheetByName(spec.name);
    if (!sheet) {
      sheet = ss.insertSheet(spec.name);
    }
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(spec.headers);
      sheet.getRange(1, 1, 1, spec.headers.length).setFontWeight("bold").setBackground("#e8eaed");
    }
  });
  
  // Delete initial default empty Sheet1 if present
  const defaultSheet = ss.getSheetByName("Sheet1");
  if (defaultSheet && ss.getSheets().length > 1 && defaultSheet.getLastRow() === 0) {
    try { ss.deleteSheet(defaultSheet); } catch (e) {}
  }
  
  Logger.log("✅ Master Sheet tabs configured successfully!");
}
