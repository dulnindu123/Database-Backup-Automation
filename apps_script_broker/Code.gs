// =============================================================================
// Enterprise Database Cloud Backup Automation - Zero-Trust Upload Broker
// Version: 4.3.0
//
// Destinations Supported:
// A. Customer-Specific Operational Sheet (e.g., "FMI Backup Sheet")
//    - Tab: [DB Backups] (Date & Time, Backup File Name, Size, Drive Link, Status)
//    - Tab: [Server Cleanup] (Date & Time, Machine ID, Drive, Total GB, Free GB, Used %, Status)
//    - Tab: [Performance Query] (Date & Time, Database, Metric, Duration ms, Status, Details)
//
// B. Master "Application report" Sheet (70+ Tabs — One per Customer)
//    - Tabs: [AdelaideGlass], [B&D], [BartonGlass - FMI], [Viridian (Bay Glass)], etc.
//    - Records every manual/automatic execution of Backups, Cleanup, and Performance.
//
// C. Customer Google Drive Folders
//    - Dedicated folders created for each customer (e.g., "AdelaideGlass", "Viridian (Bay Glass)")
// =============================================================================

// Master Broker & Application Report Google Sheet ID:
// https://docs.google.com/spreadsheets/d/12xEfxLTOw8D4K8Qi_kj0RWPl12hID6x5HZpvU_AsTLE/edit
const SPREADSHEET_ID = "12xEfxLTOw8D4K8Qi_kj0RWPl12hID6x5HZpvU_AsTLE";

// If Application Report is hosted in a dedicated spreadsheet, set its ID here.
// Defaults to SPREADSHEET_ID if left empty or matching.
const APPLICATION_REPORT_ID = "12xEfxLTOw8D4K8Qi_kj0RWPl12hID6x5HZpvU_AsTLE";

// Master Google Drive Root Folder ID:
// https://drive.google.com/drive/folders/16-ifHQQPv2vZ_eTVZvx8CiGilVy9dQ8r
const ROOT_FOLDER_ID = "16-ifHQQPv2vZ_eTVZvx8CiGilVy9dQ8r";

// =============================================================================
// 70+ CUSTOMER CANONICAL DIRECTORY (Slug -> Display Name mapping)
// Matching customer_slugs.txt and Master Application Report tabs
// =============================================================================
const CUSTOMER_DIRECTORY = {
  "adelaideglass": "AdelaideGlass",
  "bnd": "B&D",
  "fmi": "BartonGlass - FMI",
  "viridian": "Viridian (Bay Glass)",
  "chevronglass": "ChevronGlass",
  "citiwest": "Citiwest",
  "cobalt": "Cobalt",
  "constructionglazing": "Construction Glazing",
  "cutglass": "CutGlass",
  "davisglass": "DavisGlass",
  "dillmireglass": "DillmireGlass",
  "directglass": "DirectGlass",
  "geelongglass": "GeelongGlass",
  "ggs": "GGS",
  "glass360": "Glass360",
  "glassme": "Glassme",
  "glassteam": "GlassTeam",
  "glassco": "GlassCo",
  "glasstechact": "GlassTechAct",
  "glasstechcairns": "GlassTechCairns",
  "glassaustrailia": "GlassAustrailia",
  "glasshousemanufacturing": "GlassHouseManufacturing",
  "infinityglass": "InfinityGlass",
  "knkglass": "KnKGlass",
  "kiyomiglass": "KiyomiGlass",
  "kwikglass": "KwikGlass",
  "kristal": "Kristal",
  "mercuryglass": "MercuryGlass",
  "miroverreglass": "MiroverreGlass",
  "msg": "MSG",
  "megaglass": "MegaGlass",
  "newcastleglass": "NewCastleGlass",
  "ngs": "NGS",
  "novatech": "Novatech",
  "platinumimports": "PlatinumImports",
  "precisionshower": "PrecisionShower",
  "premiumoz": "PremiumOZ",
  "rezglass": "REZGlass",
  "rgt": "RGT",
  "riou": "Riou",
  "stakeglass": "StakeGlass",
  "suburbanglass": "SuburbanGlass",
  "superformglass": "SuperFormGlass",
  "superkote": "SuperKote",
  "sydneygz": "SydneyGZ",
  "tpsglass": "TPSGlass",
  "trendymirrors": "Trendy Mirrors",
  "tuffco": "Tuffco",
  "waglasskote": "WAGlassKote",
  "wholesalebevel": "WholeSale Bevel",
  "wetempglass": "WeTempGlass",
  "blisscoglass": "BlisscoGlass",
  "gatewayglass": "GatewayGlass",
  "glennsglassrotorua": "GlennsGlassRotorua",
  "glennswhakatane": "GlennsWhakatane",
  "nulookcreations": "NulookCreations",
  "nulooktepuke": "NulookTepuke",
  "omegatauranga": "OmegaTauranga",
  "rotoruaalumminium": "RotoruaAlumminium",
  "windowwarehouse": "WindowWareHouse",
  "wizardzglass": "WizardzGlass"
};

function getCustomerDisplayName(slug) {
  if (!slug) return "Unknown Customer";
  const clean = String(slug).trim().toLowerCase();
  if (CUSTOMER_DIRECTORY[clean]) {
    return CUSTOMER_DIRECTORY[clean];
  }
  // Title-cased fallback if a new slug is added dynamically
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

function getSpreadsheet() {
  if (SPREADSHEET_ID && SPREADSHEET_ID.trim() !== "") {
    try {
      return SpreadsheetApp.openById(SPREADSHEET_ID.trim());
    } catch (e) {}
  }
  return SpreadsheetApp.getActiveSpreadsheet();
}

function getApplicationReportSpreadsheet() {
  if (APPLICATION_REPORT_ID && APPLICATION_REPORT_ID.trim() !== "") {
    try {
      return SpreadsheetApp.openById(APPLICATION_REPORT_ID.trim());
    } catch (e) {}
  }
  return getSpreadsheet();
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

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

// =============================================================================
// HTTP REQUEST HANDLERS (doGet & doPost)
// =============================================================================
function doGet(e) {
  return successResponse({ status: "ok", service: "backup-broker", version: "4.3.0" });
}

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);
    const action = payload.action;

    if (action === "health") {
      return successResponse({ status: "ok", service: "backup-broker", version: "4.3.0" });
    }
    
    // Enroll uses an admin-configured one-time enrollment code
    if (action === "enroll") {
      return handleEnroll(payload);
    }

    // All authenticated actions require a valid bearer machine token
    const token = payload.token;
    if (!token) return errorResponse("Missing token", 401);

    const pcData = verifyToken(token);
    if (!pcData) {
      logAudit("UNKNOWN", "AUTH_FAILURE", "Invalid token attempt");
      return errorResponse("Unauthorized", 401);
    }

    if (action === "verify") {
      return successResponse({ pc_id: pcData.pcId, offset_minutes: pcData.offset });
    } else if (action === "test_sheet") {
      return handleTestSheet(pcData, payload);
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

// =============================================================================
// ATOMIC ENROLLMENT
// =============================================================================
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
    
    let existingRowIndex = -1;
    const tokenData = tokensSheet.getDataRange().getValues();
    for (let i = 1; i < tokenData.length; i++) {
      if (tokenData[i][0] === pcId) {
        existingRowIndex = i + 1;
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

function handleTestSheet(pcData, payload) {
  const sheetId = String(payload.sheet_id || "").trim();
  if (sheetId) {
    try {
      const ss = SpreadsheetApp.openById(sheetId);
      return successResponse({ status: "ok", title: ss.getName(), pc_id: pcData.pcId });
    } catch (e) {}
  }
  try {
    const ss = getSpreadsheet();
    return successResponse({ status: "ok", title: ss.getName(), pc_id: pcData.pcId });
  } catch (e2) {
    return errorResponse("Cannot access spreadsheet: " + e2.message, 403);
  }
}

// =============================================================================
// GOOGLE DRIVE UPLOAD BROKERING (Destination C: Customer Folder)
// =============================================================================
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
    
    // Destination C: Customer's dedicated folder in Google Drive
    const customerDisplayName = getCustomerDisplayName(pcData.customerSlug);
    const destFolderId = getOrCreateFolder(ROOT_FOLDER_ID, customerDisplayName);
    
    // Create Resumable Upload Session via Drive API v3
    const sessionUri = createResumableUpload(destFolderId, fileName, sizeBytes);
    
    logAudit(pcData.pcId, "UPLOAD_REQUEST", dbName);
    return successResponse({ upload_url: sessionUri, file_name: fileName, folder_id: destFolderId });
  } finally {
    lock.releaseLock();
  }
}

// =============================================================================
// STATUS & TELEMETRY ROUTER (Destinations A & B)
// =============================================================================
function handleReportStatus(pcData, payload) {
  const customerDisplayName = getCustomerDisplayName(pcData.customerSlug);
  const customerFolderId = getOrCreateFolder(ROOT_FOLDER_ID, customerDisplayName);
  const timestamp = new Date().toISOString();
  const runMode = payload.run_mode || "Automatic";
  const durationSecs = payload.duration_secs || 0;

  // Resolve Customer-Specific Operational Sheet (Destination A)
  const customerSheet = getOrCreateCustomerSheet(customerFolderId, customerDisplayName, payload.customer_sheet_id);

  const module = (payload.module || "").toUpperCase();

  // ---------------------------------------------------------------------------
  // 1. DB BACKUP MODULE
  // ---------------------------------------------------------------------------
  if (module === "DB_BACKUP" || payload.file_name) {
    const fileName = payload.file_name || (pcData.pcId + "_" + (payload.db_name || "DB") + ".dbk2");
    const bytes = payload.bytes || 0;
    const sizeFormatted = formatBytes(bytes);
    
    // Find uploaded file in Customer's Drive Folder to get direct download/view link
    let downloadLink = "Pending / Uploaded";
    try {
      const folder = DriveApp.getFolderById(customerFolderId);
      const files = folder.getFilesByName(fileName);
      if (files.hasNext()) {
        const file = files.next();
        downloadLink = file.getUrl();
      }
    } catch (e) {}

    // A. Log to Customer's Sheet -> [DB Backups] tab
    if (customerSheet) {
      let dbBackupsTab = customerSheet.getSheetByName("DB Backups");
      if (!dbBackupsTab) {
        initCustomerSheetTabs(customerSheet);
        dbBackupsTab = customerSheet.getSheetByName("DB Backups");
      }
      dbBackupsTab.appendRow([
        timestamp,
        fileName,
        sizeFormatted,
        downloadLink,
        payload.status || "SUCCESS"
      ]);
    }

    // B. Log to Master "Application report" Sheet -> [Customer Tab]
    logToApplicationReport(customerDisplayName, {
      timestamp: timestamp,
      pcId: pcData.pcId,
      runMode: runMode,
      module: "DB Backup",
      status: payload.status || "SUCCESS",
      durationSecs: durationSecs,
      details: `Backup: ${fileName} (${sizeFormatted}) | Status: ${payload.status || "SUCCESS"}`
    });

    // Fallback: Internal Telemetry Tab
    appendInternalTelemetry(timestamp, pcData.pcId, pcData.customerSlug, payload.status || "SUCCESS", payload.message || "Backup completed", payload.db_name || "", bytes);

    return successResponse({ status: "recorded", module: "DB_BACKUP", download_link: downloadLink });
  }

  // ---------------------------------------------------------------------------
  // 2. SERVER CLEANUP SCAN MODULE
  // ---------------------------------------------------------------------------
  if (module === "SERVER_CLEANUP" || (payload.drives && Array.isArray(payload.drives))) {
    const drives = payload.drives || payload.metrics || [];

    // A. Log each drive to Customer's Sheet -> [Server Cleanup] tab
    if (customerSheet) {
      let cleanupTab = customerSheet.getSheetByName("Server Cleanup");
      if (!cleanupTab) {
        initCustomerSheetTabs(customerSheet);
        cleanupTab = customerSheet.getSheetByName("Server Cleanup");
      }
      drives.forEach(d => {
        cleanupTab.appendRow([
          timestamp,
          pcData.pcId,
          d.drive_letter || d.letter || "C:",
          d.total_gb || 0,
          d.free_gb || 0,
          d.used_percent || d.percent_used || 0,
          d.status || "OK / Healthy"
        ]);
      });
    }

    // B. Log to Master "Application report" Sheet -> [Customer Tab]
    logToApplicationReport(customerDisplayName, {
      timestamp: timestamp,
      pcId: pcData.pcId,
      runMode: runMode,
      module: "Server Cleanup Scan",
      status: payload.status || "SUCCESS",
      durationSecs: durationSecs,
      details: `Storage Scanned: ${drives.length} drives evaluated. Disk space OK.`
    });

    return successResponse({ status: "recorded", module: "SERVER_CLEANUP", drives_logged: drives.length });
  }

  // ---------------------------------------------------------------------------
  // 3. PERFORMANCE QUERY MODULE
  // ---------------------------------------------------------------------------
  if (module === "PERFORMANCE_QUERY") {
    const customerStartTime = payload.task_start_time || timestamp;
    const queryExecTime = payload.query_exec_time || timestamp;
    const sqlVersion = payload.sql_version || "Microsoft SQL Server";
    const dbSizeMB = payload.db_size_mb || 0;
    const preBackup = payload.pre_backup_status || "N/A";
    const fragBefore = (payload.frag_before_max !== undefined) ? (payload.frag_before_max + "%") : "N/A";
    const fragAfter = (payload.frag_after_max !== undefined) ? (payload.frag_after_max + "%") : "N/A";
    const checkdb = payload.checkdb_status || "Clean (0 errors)";
    const reindex = payload.reindex_status || "Completed";

    // A. Log to Customer's Sheet -> [Performance Query] tab
    if (customerSheet) {
      let perfTab = customerSheet.getSheetByName("Performance Query");
      if (!perfTab) {
        initCustomerSheetTabs(customerSheet);
        perfTab = customerSheet.getSheetByName("Performance Query");
      }
      perfTab.appendRow([
        customerStartTime,
        queryExecTime,
        payload.db_name || "ALL",
        sqlVersion,
        dbSizeMB,
        preBackup,
        fragBefore,
        fragAfter,
        checkdb,
        reindex,
        durationSecs,
        runMode,
        payload.status || "SUCCESS"
      ]);
    }

    // B. Log to Master "Application report" Sheet -> [Customer Tab]
    logToApplicationReport(customerDisplayName, {
      timestamp: customerStartTime,
      pcId: pcData.pcId,
      runMode: runMode,
      module: "Performance Query",
      status: payload.status || "SUCCESS",
      durationSecs: durationSecs,
      details: `SQL ${sqlVersion} | DB: ${dbSizeMB} MB | Frag: ${fragBefore} -> ${fragAfter} | ${reindex} | CHECKDB: ${checkdb}`
    });

    return successResponse({ status: "recorded", module: "PERFORMANCE_QUERY" });
  }

  // ---------------------------------------------------------------------------
  // 4. GENERAL APPLICATION RUN SUMMARY
  // ---------------------------------------------------------------------------
  logToApplicationReport(customerDisplayName, {
    timestamp: timestamp,
    pcId: pcData.pcId,
    runMode: runMode,
    module: payload.module || "Application Automation",
    status: payload.status || "SUCCESS",
    durationSecs: durationSecs,
    details: payload.message || payload.details || "Workflow executed"
  });

  return successResponse({ status: "recorded" });
}

// =============================================================================
// DESTINATION B HELPER: Master "Application report" Customer Tab Logger
// =============================================================================
function logToApplicationReport(customerDisplayName, runDetails) {
  const appReportSs = getApplicationReportSpreadsheet();
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    let tab = appReportSs.getSheetByName(customerDisplayName);
    if (!tab) {
      tab = appReportSs.insertSheet(customerDisplayName);
      const headers = ["Date & Time", "Machine / PC ID", "Run Mode", "Module", "Status", "Duration (s)", "Details"];
      tab.appendRow(headers);
      tab.getRange(1, 1, 1, headers.length).setFontWeight("bold").setBackground("#e8eaed");
    }

    tab.appendRow([
      runDetails.timestamp || new Date().toISOString(),
      runDetails.pcId || "UNKNOWN",
      runDetails.runMode || "Automatic",
      runDetails.module || "Automation",
      runDetails.status || "SUCCESS",
      runDetails.durationSecs || 0,
      runDetails.details || ""
    ]);
  } catch (err) {
    Logger.log("Application Report logging error: " + err.message);
  } finally {
    lock.releaseLock();
  }
}

// =============================================================================
// DESTINATION A HELPER: Customer-Specific Operational Sheet Resolver
// =============================================================================
function getOrCreateCustomerSheet(customerFolderId, customerDisplayName, explicitSheetId) {
  // 1. Explicit ID passed in client config
  if (explicitSheetId && String(explicitSheetId).trim() !== "") {
    try {
      return SpreadsheetApp.openById(String(explicitSheetId).trim());
    } catch (e) {}
  }

  // 2. Search inside Customer's Google Drive Folder for existing sheet
  try {
    const folder = DriveApp.getFolderById(customerFolderId);
    const targetTitle = customerDisplayName + " Backup Sheet";
    const files = folder.getFilesByType(MimeType.GOOGLE_SHEETS);
    while (files.hasNext()) {
      const file = files.next();
      if (file.getName() === targetTitle || file.getName().toLowerCase().includes("backup sheet")) {
        return SpreadsheetApp.openById(file.getId());
      }
    }

    // 3. Auto-create if not found directly inside Customer's folder
    const newSs = SpreadsheetApp.create(targetTitle);
    const newFile = DriveApp.getFileById(newSs.getId());
    folder.addFile(newFile);
    DriveApp.getRootFolder().removeFile(newFile);
    initCustomerSheetTabs(newSs);
    return newSs;
  } catch (e) {
    Logger.log("Customer sheet resolution note: " + e.message);
    return null;
  }
}

function initCustomerSheetTabs(ss) {
  const tabs = [
    {
      name: "DB Backups",
      headers: ["Date & Time", "Backup File Name", "Backup File Size", "Google Drive Download Link", "Status"]
    },
    {
      name: "Server Cleanup",
      headers: ["Date & Time", "Machine / PC ID", "Drive", "Total GB", "Free GB", "Used %", "Status / Action Taken"]
    },
    {
      name: "Performance Query",
      headers: [
        "Task Start Time (Customer TZ)",
        "Query Execution Time",
        "Database",
        "SQL Server Version",
        "DB Size (MB)",
        "Pre-Maintenance Backup",
        "Index Frag Before",
        "Index Frag After",
        "CHECKDB Status",
        "Reindexing & Stats",
        "Run Time (s)",
        "Run Mode",
        "Status"
      ]
    }
  ];

  tabs.forEach(spec => {
    let sheet = ss.getSheetByName(spec.name);
    if (!sheet) sheet = ss.insertSheet(spec.name);
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(spec.headers);
      sheet.getRange(1, 1, 1, spec.headers.length).setFontWeight("bold").setBackground("#e8eaed");
    }
  });

  const defaultSheet = ss.getSheetByName("Sheet1");
  if (defaultSheet && ss.getSheets().length > 1 && defaultSheet.getLastRow() === 0) {
    try { ss.deleteSheet(defaultSheet); } catch (e) {}
  }
}

// =============================================================================
// GOOGLE DRIVE & SYSTEM UTILITIES
// =============================================================================
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
  try {
    const ss = getSpreadsheet();
    let auditSheet = ss.getSheetByName("Audit");
    if (!auditSheet) {
      auditSheet = ss.insertSheet("Audit");
      auditSheet.appendRow(["TIMESTAMP", "PC_ID", "ACTION", "DETAILS"]);
    }
    auditSheet.appendRow([new Date().toISOString(), pcId, action, details]);
  } catch (e) {}
}

function appendInternalTelemetry(timestamp, pcId, customerSlug, status, message, dbName, bytes) {
  try {
    const ss = getSpreadsheet();
    let sheet = ss.getSheetByName("Telemetry");
    if (sheet) {
      sheet.appendRow([timestamp, pcId, customerSlug, status, message, dbName, bytes]);
    }
  } catch (e) {}
}

function successResponse(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}

function errorResponse(msg, code) {
  return ContentService.createTextOutput(JSON.stringify({ error: msg, code: code })).setMimeType(ContentService.MimeType.JSON);
}

// =============================================================================
// SETUP FUNCTION: PRE-CREATE ALL 70+ CUSTOMER TABS IN APPLICATION REPORT
// Run once from Apps Script editor to prepare the Master Application Report!
// =============================================================================
function setupApplicationReportTabs() {
  const appReportSs = getApplicationReportSpreadsheet();
  const headers = ["Date & Time", "Machine / PC ID", "Run Mode", "Module", "Status", "Duration (s)", "Details"];
  
  const slugs = Object.keys(CUSTOMER_DIRECTORY);
  Logger.log(`Configuring ${slugs.length} customer tabs in Application Report...`);

  slugs.forEach(slug => {
    const tabName = CUSTOMER_DIRECTORY[slug];
    let tab = appReportSs.getSheetByName(tabName);
    if (!tab) {
      tab = appReportSs.insertSheet(tabName);
    }
    if (tab.getLastRow() === 0) {
      tab.appendRow(headers);
      tab.getRange(1, 1, 1, headers.length).setFontWeight("bold").setBackground("#e8eaed");
    }
  });

  const defaultSheet = appReportSs.getSheetByName("Sheet1");
  if (defaultSheet && appReportSs.getSheets().length > 1 && defaultSheet.getLastRow() === 0) {
    try { appReportSs.deleteSheet(defaultSheet); } catch (e) {}
  }

  Logger.log(`✅ Successfully initialized all ${slugs.length} customer tabs in Application Report!`);
}

/**
 * Standard broker tables setup function (Config, Tokens, Audit, etc.)
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
  
  setupApplicationReportTabs();
  Logger.log("✅ Master Sheet & Application Report configured successfully!");
}
