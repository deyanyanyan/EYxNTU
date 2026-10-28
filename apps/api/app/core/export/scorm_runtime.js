/* SCORM 1.2 run-time API for the in-app course preview (app/core/export/scorm_preview.py).
 *
 * Injected at the top of every SCO page the preview serves, so the package's own scorm.js
 * finds window.API as it would in an LMS frame. The page runs sandboxed in an opaque
 * origin, so this API keeps the learner record in memory and reports every call, with the
 * record after it, to the preview player by postMessage. The launch state (earlier status,
 * score, location, suspend data) arrives in the URL fragment as lms=<JSON>.
 */
(function () {
  "use strict";
  var launch = {};
  try {
    var found = /[#&]lms=([^&]*)/.exec(location.hash);
    launch = (found && JSON.parse(decodeURIComponent(found[1]))) || {};
  } catch (e) {
    launch = {};
  }
  var saved = launch.cmi || {};

  var ERRORS = {
    "0": "No error",
    "101": "General exception",
    "201": "Invalid argument error",
    "202": "Element cannot have children",
    "203": "Element not an array - cannot have count",
    "301": "Not initialized",
    "401": "Not implemented error",
    "402": "Invalid set value, element is a keyword",
    "403": "Element is read only",
    "404": "Element is write only",
    "405": "Incorrect data type"
  };
  var TIMESPAN = /^\d{2,4}:\d{2}:\d{2}(\.\d{1,2})?$/;
  function decimal(v) { return v === "" || (/^\d+(\.\d+)?$/.test(v) && Number(v) <= 100); }
  function oneOf(list) { return function (v) { return list.indexOf(v) !== -1; }; }
  function upTo(n) { return function (v) { return v.length <= n; }; }

  // element -> [access, value check]; access is "ro", "wo" or "rw"
  var MODEL = {
    "cmi.core.student_id": ["ro"],
    "cmi.core.student_name": ["ro"],
    "cmi.core.lesson_location": ["rw", upTo(255)],
    "cmi.core.credit": ["ro"],
    "cmi.core.lesson_status": ["rw", oneOf(["passed", "completed", "failed", "incomplete", "browsed"])],
    "cmi.core.entry": ["ro"],
    "cmi.core.score.raw": ["rw", decimal],
    "cmi.core.score.max": ["rw", decimal],
    "cmi.core.score.min": ["rw", decimal],
    "cmi.core.total_time": ["ro"],
    "cmi.core.lesson_mode": ["ro"],
    "cmi.core.exit": ["wo", oneOf(["time-out", "suspend", "logout", ""])],
    "cmi.core.session_time": ["wo", function (v) { return TIMESPAN.test(v); }],
    "cmi.suspend_data": ["rw", upTo(4096)],
    "cmi.launch_data": ["ro"],
    "cmi.comments": ["rw", upTo(4096)],
    "cmi.comments_from_lms": ["ro"],
    "cmi.student_data.mastery_score": ["ro"]
  };
  var KEYWORDS = {
    "cmi.core._children": "student_id,student_name,lesson_location,credit,lesson_status,entry,score,total_time,lesson_mode,exit,session_time",
    "cmi.core.score._children": "raw,min,max",
    "cmi.student_data._children": "mastery_score",
    // The preview records no objectives or interactions, so a SCO that counts them sees none.
    "cmi.objectives._count": "0",
    "cmi.interactions._count": "0"
  };
  // Valid SCORM 1.2 elements this preview does not record.
  var UNSUPPORTED = /^cmi\.(objectives|interactions|student_preference)\.|^cmi\.student_data\.(max_time_allowed|time_limit_action)$/;

  var values = {
    "cmi.core.student_id": launch.student_id || "preview",
    "cmi.core.student_name": launch.student_name || "Learner, Preview",
    "cmi.core.lesson_location": saved.lesson_location || "",
    "cmi.core.credit": launch.credit || "credit",
    "cmi.core.lesson_status": saved.lesson_status || "not attempted",
    "cmi.core.entry": launch.entry == null ? "ab-initio" : launch.entry,
    "cmi.core.score.raw": saved.score_raw || "",
    "cmi.core.score.max": saved.score_max || "",
    "cmi.core.score.min": saved.score_min || "",
    "cmi.core.total_time": launch.total_time || "0000:00:00.00",
    "cmi.core.lesson_mode": launch.lesson_mode || "normal",
    "cmi.core.exit": "",
    "cmi.core.session_time": "",
    "cmi.suspend_data": saved.suspend_data || "",
    "cmi.launch_data": launch.launch_data || "",
    "cmi.comments": saved.comments || "",
    "cmi.comments_from_lms": "",
    "cmi.student_data.mastery_score": launch.mastery_score == null ? "" : String(launch.mastery_score)
  };
  var phase = "launched"; // -> "running" after LMSInitialize -> "finished" after LMSFinish
  var lastError = "0";

  function record() {
    return {
      lesson_status: values["cmi.core.lesson_status"],
      score_raw: values["cmi.core.score.raw"],
      score_min: values["cmi.core.score.min"],
      score_max: values["cmi.core.score.max"],
      lesson_location: values["cmi.core.lesson_location"],
      suspend_data: values["cmi.suspend_data"],
      comments: values["cmi.comments"],
      exit: values["cmi.core.exit"],
      session_time: values["cmi.core.session_time"]
    };
  }
  function post(message) {
    message.channel = "lms-preview";
    message.sco = launch.sco;
    message.attempt = launch.attempt;
    if (window.parent !== window) window.parent.postMessage(message, "*");
  }
  function answer(fn, args, result, code) {
    lastError = code || "0";
    post({ type: "call", fn: fn, args: args, result: result, error: lastError, record: record() });
    return result;
  }
  function blank(arg) { return arg === "" || arg === undefined; }
  function unknown(element) { return UNSUPPORTED.test(element) ? "401" : "201"; }

  window.API = {
    LMSInitialize: function (arg) {
      if (!blank(arg)) return answer("LMSInitialize", [String(arg)], "false", "201");
      if (phase !== "launched") return answer("LMSInitialize", [""], "false", "101");
      phase = "running";
      return answer("LMSInitialize", [""], "true");
    },
    LMSFinish: function (arg) {
      if (!blank(arg)) return answer("LMSFinish", [String(arg)], "false", "201");
      if (phase !== "running") return answer("LMSFinish", [""], "false", "301");
      phase = "finished";
      return answer("LMSFinish", [""], "true");
    },
    LMSGetValue: function (element) {
      element = String(element);
      if (phase !== "running") return answer("LMSGetValue", [element], "", "301");
      if (Object.prototype.hasOwnProperty.call(KEYWORDS, element)) return answer("LMSGetValue", [element], KEYWORDS[element]);
      var spec = MODEL[element];
      if (!spec) {
        var code = /\._children$/.test(element) ? "202" : /\._count$/.test(element) ? "203" : unknown(element);
        return answer("LMSGetValue", [element], "", code);
      }
      if (spec[0] === "wo") return answer("LMSGetValue", [element], "", "404");
      return answer("LMSGetValue", [element], values[element]);
    },
    LMSSetValue: function (element, value) {
      element = String(element);
      value = value == null ? "" : String(value);
      var args = [element, value];
      if (phase !== "running") return answer("LMSSetValue", args, "false", "301");
      if (/\._(children|count)$/.test(element)) return answer("LMSSetValue", args, "false", "402");
      var spec = MODEL[element];
      if (!spec) return answer("LMSSetValue", args, "false", unknown(element));
      if (spec[0] === "ro") return answer("LMSSetValue", args, "false", "403");
      if (spec[1] && !spec[1](value)) return answer("LMSSetValue", args, "false", "405");
      values[element] = value;
      return answer("LMSSetValue", args, "true");
    },
    LMSCommit: function (arg) {
      if (!blank(arg)) return answer("LMSCommit", [String(arg)], "false", "201");
      if (phase !== "running") return answer("LMSCommit", [""], "false", "301");
      return answer("LMSCommit", [""], "true");
    },
    // Error queries do not change the last error, so they are not reported as calls.
    LMSGetLastError: function () { return lastError; },
    LMSGetErrorString: function (code) { return ERRORS[String(code)] || ""; },
    LMSGetDiagnostic: function (code) { return ERRORS[blank(code) ? lastError : String(code)] || ""; }
  };
  post({ type: "launch" });
})();
