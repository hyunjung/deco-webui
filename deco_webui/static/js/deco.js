// Copyright 2012 Stanford University InfoLab
// See LICENSE for details.

//
// typeahead
//
$("textarea#query").typeahead({
  source: ["SELECT ", "FROM ", "WHERE ", "ATLEAST ",
           "CREATE ", "ALTER ", "DROP ",
           "TABLE ", "COLUMN ", "FETCHRULE ", "FUNCTION ",
           "USING ", "BOOLEAN", "FLOAT", "INTEGER", "VARCHAR"],
  matcher: function(item) {
    if (this.query.length != this.$element.context.selectionStart) {
      return false;
    }
    var lastDelimIndex = Math.max(this.query.lastIndexOf(" "),
                                  this.query.lastIndexOf("\n"));
    var lastToken = this.query.substring(lastDelimIndex + 1).toUpperCase();
    return lastToken.length > 0 && item.indexOf(lastToken) == 0;
  },
  highlighter: function(item) {
    var lastDelimIndex = Math.max(this.query.lastIndexOf(" "),
                                  this.query.lastIndexOf("\n"));
    var lastToken = this.query.substring(lastDelimIndex + 1).toUpperCase();
    return '<strong>' + lastToken + '</strong>' + item.substring(lastToken.length);
  },
  select: function() {
    var lastDelimIndex = Math.max(this.query.lastIndexOf(" "),
                                  this.query.lastIndexOf("\n"));
    var val = this.$menu.find('.active').attr('data-value');
    this.$element.val(this.query.substring(0, lastDelimIndex + 1) + val);
    return this.hide();
  }
});

//
// history
//
if (typeof(localStorage) == 'undefined' || localStorage.history == null) {
  queries = [];
} else {
  queries = JSON.parse(localStorage.history);
}
current = queries.length;
toggleHistoryButtons();

function toggleHistoryButtons() {
  $("button#prev").attr("disabled", current == 0);
  $("button#next").attr("disabled", current == queries.length);
}

function addToHistory(query) {
  if (query != queries[queries.length - 1]) {
    if (queries.length >= 30) {
      queries.shift();
    }
    queries.push(query);

    if (typeof(localStorage) != 'undefined') {
      localStorage.history = JSON.stringify(queries);
    }
  }
  current = queries.length - 1;
  toggleHistoryButtons();
}

$("button#prev").click(function(event) {
  event.preventDefault();
  if (current > 0) {
    --current;
  }
  $("textarea#query").val(queries[current]);
  toggleHistoryButtons();
});
$("button#next").click(function(event) {
  event.preventDefault();
  if (current < queries.length) {
    ++current;
  }
  $("textarea#query").val((current < queries.length) ? queries[current] : '');
  toggleHistoryButtons();
});

//
// everything else
//
function alertSuccess(msg) {$("div#alert").html('<div class="alert alert-success"><a class="close" data-dismiss="alert" href="#">&times;</a>' + msg + '</div>');}
function alertError(msg) {$("div#alert").html('<div class="alert alert-error"><a class="close" data-dismiss="alert" href="#">&times;</a>' + msg + '</div>');}
function clearAlert() {$("div#alert").empty();}
function clearResult() {$("div#result").empty();}
function enableSubmitButtons() {$("button:submit").attr("disabled", false);}
function disableSubmitButtons() {$("button:submit").attr("disabled", true);}
function enableStopButton() {$("button#stop").attr("disabled", false);}
function disableStopButton() {$("button#stop").attr("disabled", true);}
function hideLoadingImage() {$("img#loading").hide();}
function showLoadingImage() {$("img#loading").show();}

disableSubmitButtons();
disableStopButton();
hideLoadingImage();

if (!window.WebSocket) {
  if (window.MozWebSocket) {
    window.WebSocket = window.MozWebSocket;
  } else {
    alertError("Your browser doesn't support WebSocket.");
  }
}
if ($.browser.mozilla) {
  $(document).keypress(function(e) {
    if (e.keyCode == 27) {
      e.preventDefault();
    }
  });
}

visApiLoaded = false;
function loadVis() {
  google.load("visualization", "1", {"packages":["table", "orgchart"], "callback": visLoaded});
}
function visLoaded() {
  visApiLoaded = true;
  if (ws1.readyState == WebSocket.OPEN) {
    enableSubmitButtons();
    alertSuccess('Connected to the server.');
  }
}
$(function() {
  var script = document.createElement("script");
  script.src = "http://www.google.com/jsapi?callback=loadVis";
  script.type = "text/javascript";
  document.getElementsByTagName("head")[0].appendChild(script);
});

ws1 = new WebSocket('ws://' + location.host + '/websocket');
ws1.onopen = function(e) {
  if (visApiLoaded) {
    enableSubmitButtons();
    alertSuccess('Connected to the server.');
  }
};
ws1.onerror = function(e) {
  disableSubmitButtons();
  disableStopButton();
  hideLoadingImage();
  alertError('Connection error occurred. Please reload.');
};
ws1.onclose = function(e) {
  disableSubmitButtons();
  disableStopButton();
  hideLoadingImage();
  alertError('Disconnected from the server. Please reload.');
};
ws1.onmessage = function(e) {
  var response = JSON.parse(e.data);
  if (response.a == 'd') {
    result = new google.visualization.DataTable();
    for (var j = 0; j < response.c.length; ++j) {
      result.addColumn('string', response.c[j]);
    }
    table = new google.visualization.Table($("div#result").get(0));
    table.draw(result);
  } else if (response.a == 'p') {
    result.addRow(response.r);
  } else if (response.a == 's') {
    table.draw(result, {allowHtml:true, showRowNumber:true});
  } else if (response.a == 'a') {
    result.addRow(response.r);
    table.draw(result, {allowHtml:true, showRowNumber:true});
  } else if (response.a == 'r') {
    var filters = [];
    for (var j = 0; j < response.r.length; ++j) {
      filters.push({column: j, value: response.r[j].v});
    }
    result.removeRow(result.getFilteredRows(filters)[0]);
    table.draw(result, {allowHtml:true, showRowNumber:true});
  } else if (response.a == 't') {
    enableSubmitButtons();
    disableStopButton();
    hideLoadingImage();
  } else if (response.error != null) {
    alertError(response.error);
    enableSubmitButtons();
    disableStopButton();
    hideLoadingImage();
  } else {
    alertSuccess('Success!');
    enableSubmitButtons();
    disableStopButton();
    hideLoadingImage();
  }
};

ws2 = new WebSocket('ws://' + location.host + '/log');
ws2.onopen = function(e) {
  $("table#log").append('<tr><td style="width:72px;"></td><td style="width:72px;"></td><td class="span10">log stream opened</td></tr>');
}
ws2.onerror = function(e) {
  $("table#log").append('<tr><td></td><td></td><td>log stream error</td></tr>');
}
ws2.onclose = function(e) {
  $("table#log").append('<tr><td></td><td></td><td>log stream closed</td></tr>');
}
ws2.onmessage = function(e) {
  var log = JSON.parse(e.data);
  $("table#log").append('<tr><td>' + log.join('</td><td>') + '</td></tr>');
}

$(window).bind('beforeunload', function() {
  if (!$("button#stop").attr("disabled")) {
    return 'Your query is still running.';
  }
});

$(window).bind('unload', function() {
  ws1.close();
  ws2.close();
});

$("button#execute").click(function(event) {
  event.preventDefault();

  clearAlert();
  clearResult();
  addToHistory($("textarea#query").val());

  disableSubmitButtons();
  showLoadingImage();

  if (event.shiftKey) {
    ws1.send('b' + $("textarea#query").val());
  } else {
    enableStopButton();
    ws1.send('d' + $("textarea#query").val());
  }
});

$("button#stop").click(function(event) {
  event.preventDefault();

  $.ajax({
    type: 'GET',
    url: '/stopexecution',
    success: function(response) {
      disableStopButton();
    },
    error: function(jqXHR, textStatus, errorThrown) {
      if (errorThrown != null && errorThrown != '') {
        alertError(errorThrown);
      } else {
        alertError(textStatus);
      }
    }
  });
});

$("button#explain").click(function(event) {
  event.preventDefault();

  clearAlert();
  clearResult();
  addToHistory($("textarea#query").val());

  disableSubmitButtons();
  showLoadingImage();

  $.ajax({
    type: 'POST',
    url: '/explain',
    data: $("form#query-form").serialize(),
    dataType: 'json',
    success: function(response) {
      if (response.error != null) {
        alertError(response.error);
      } else if (response.plan != null) {
        var plan = new google.visualization.DataTable();
        plan.addColumn('string', 'name');
        plan.addColumn('string', 'parent');
        plan.addColumn('string', 'tooltip');
        plan.addRows(response.plan);
        var chart = new google.visualization.OrgChart($("div#result").get(0));
        chart.draw(plan, {allowHtml:true});
      }
      enableSubmitButtons();
      hideLoadingImage();
    },
    error: function(jqXHR, textStatus, errorThrown) {
      if (errorThrown != null && errorThrown != '') {
        alertError(errorThrown);
      } else {
        alertError(textStatus);
      }
      enableSubmitButtons();
      hideLoadingImage();
    }
  });
});
