

(function(globals) {

  var django = globals.django || (globals.django = {});

  
  django.pluralidx = function(n) {
    var v=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);
    if (typeof(v) == 'boolean') {
      return v ? 1 : 0;
    } else {
      return v;
    }
  };
  

  /* gettext library */

  django.catalog = django.catalog || {};
  
  var newcatalog = {
    "%(sel)s of %(cnt)s selected": [
      "%(sel)s \u043e\u0434 %(cnt)s \u0438\u0437\u0430\u0431\u0440\u0430\u043d", 
      "%(sel)s \u043e\u0434 %(cnt)s \u0438\u0437\u0430\u0431\u0440\u0430\u043d\u0430", 
      "%(sel)s \u043e\u0434 %(cnt)s \u0438\u0437\u0430\u0431\u0440\u0430\u043d\u0438\u0445"
    ], 
    "6 a.m.": "18\u0447", 
    "Available %s": "\u0414\u043e\u0441\u0442\u0443\u043f\u043d\u0438 %s", 
    "Cancel": "\u041f\u043e\u043d\u0438\u0448\u0442\u0438", 
    "Choose": "\u0418\u0437\u0430\u0431\u0435\u0440\u0438", 
    "Choose a time": "\u041e\u0434\u0430\u0431\u0438\u0440 \u0432\u0440\u0435\u043c\u0435\u043d\u0430", 
    "Choose all": "\u0418\u0437\u0430\u0431\u0435\u0440\u0438 \u0441\u0432\u0435", 
    "Chosen %s": "\u0418\u0437\u0430\u0431\u0440\u0430\u043d\u043e \u201e%s\u201c", 
    "Click to choose all %s at once.": "\u0418\u0437\u0430\u0431\u0435\u0440\u0438\u0442\u0435 \u0441\u0432\u0435 \u201e%s\u201c \u043e\u0434\u0458\u0435\u0434\u043d\u043e\u043c.", 
    "Click to remove all chosen %s at once.": "\u0423\u043a\u043b\u043e\u043d\u0438\u0442\u0435 \u0441\u0432\u0435 \u0438\u0437\u0430\u0431\u0440\u0430\u043d\u0435 \u201e%s\u201c \u043e\u0434\u0458\u0435\u0434\u043d\u043e\u043c.", 
    "Filter": "\u0424\u0438\u043b\u0442\u0435\u0440", 
    "Hide": "\u0421\u0430\u043a\u0440\u0438\u0458", 
    "Midnight": "\u041f\u043e\u043d\u043e\u045b", 
    "Noon": "\u041f\u043e\u0434\u043d\u0435", 
    "Now": "\u0422\u0440\u0435\u043d\u0443\u0442\u043d\u043e \u0432\u0440\u0435\u043c\u0435", 
    "Remove": "\u0423\u043a\u043b\u043e\u043d\u0438", 
    "Remove all": "\u0423\u043a\u043b\u043e\u043d\u0438 \u0441\u0432\u0435", 
    "Show": "\u041f\u043e\u043a\u0430\u0436\u0438", 
    "This is the list of available %s. You may choose some by selecting them in the box below and then clicking the \"Choose\" arrow between the two boxes.": "\u041e\u0432\u043e \u0458\u0435 \u043b\u0438\u0441\u0442\u0430 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0438\u0445 \u201e%s\u201c. \u041c\u043e\u0436\u0435\u0442\u0435 \u0438\u0437\u0430\u0431\u0440\u0430\u0442\u0438 \u0435\u043b\u0435\u043c\u0435\u043d\u0442\u0435 \u0442\u0430\u043a\u043e \u0448\u0442\u043e \u045b\u0435\u0442\u0435 \u0438\u0445 \u0438\u0437\u0430\u0431\u0440\u0430\u0442\u0438 \u0443 \u043b\u0438\u0441\u0442\u0438 \u0438 \u043a\u043b\u0438\u043a\u043d\u0443\u0442\u0438 \u043d\u0430 \u201e\u0418\u0437\u0430\u0431\u0435\u0440\u0438\u201c.", 
    "This is the list of chosen %s. You may remove some by selecting them in the box below and then clicking the \"Remove\" arrow between the two boxes.": "\u041e\u0432\u043e \u0458\u0435 \u043b\u0438\u0441\u0442\u0430 \u0438\u0437\u0430\u0431\u0440\u0430\u043d\u0438\u0445 \u201e%s\u201c. \u041c\u043e\u0436\u0435\u0442\u0435 \u0443\u043a\u043b\u043e\u043d\u0438\u0442\u0438 \u0435\u043b\u0435\u043c\u0435\u043d\u0442\u0435 \u0442\u0430\u043a\u043e \u0448\u0442\u043e \u045b\u0435\u0442\u0435 \u0438\u0445 \u0438\u0437\u0430\u0431\u0440\u0430\u0442\u0438 \u0443 \u043b\u0438\u0441\u0442\u0438 \u0438 \u043a\u043b\u0438\u043a\u043d\u0443\u0442\u0438 \u043d\u0430 \u201e\u0423\u043a\u043b\u043e\u043d\u0438\u201c.", 
    "Today": "\u0414\u0430\u043d\u0430\u0441", 
    "Tomorrow": "\u0421\u0443\u0442\u0440\u0430", 
    "Type into this box to filter down the list of available %s.": "\u0424\u0438\u043b\u0442\u0440\u0438\u0440\u0430\u0458\u0442\u0435 \u043b\u0438\u0441\u0442\u0443 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0438\u0445 \u0435\u043b\u0435\u043c\u0435\u043d\u0430\u0442\u0430 \u201e%s\u201c.", 
    "Yesterday": "\u0408\u0443\u0447\u0435", 
    "You have selected an action, and you haven't made any changes on individual fields. You're probably looking for the Go button rather than the Save button.": "\u0418\u0437\u0430\u0431\u0440\u0430\u043b\u0438 \u0441\u0442\u0435 \u0430\u043a\u0446\u0438\u0458\u0443 \u0430\u043b\u0438 \u043d\u0438\u0441\u0442\u0435 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0438 \u043d\u0438 \u0458\u0435\u0434\u043d\u043e \u043f\u043e\u0459\u0435.", 
    "You have selected an action, but you haven't saved your changes to individual fields yet. Please click OK to save. You'll need to re-run the action.": "\u0418\u0437\u0430\u0431\u0440\u0430\u043b\u0438 \u0441\u0442\u0435 \u0430\u043a\u0446\u0438\u0458\u0443 \u0430\u043b\u0438 \u043d\u0438\u0441\u0442\u0435 \u0441\u0430\u0447\u0443\u0432\u0430\u043b\u0438 \u043f\u0440\u043e\u043c\u0435\u043d\u0435 \u043f\u043e\u0459\u0430.", 
    "You have unsaved changes on individual editable fields. If you run an action, your unsaved changes will be lost.": "\u0418\u043c\u0430\u0442\u0435 \u043d\u0435\u0441\u0430\u0447\u0438\u0432\u0430\u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0435. \u0410\u043a\u043e \u043f\u043e\u043a\u0440\u0435\u043d\u0435\u0442\u0435 \u0430\u043a\u0446\u0438\u0458\u0443, \u0438\u0437\u043c\u0435\u043d\u0435 \u045b\u0435 \u0431\u0438\u0442\u0438 \u0438\u0437\u0433\u0443\u0431\u0459\u0435\u043d\u0435."
  };
  for (var key in newcatalog) {
    django.catalog[key] = newcatalog[key];
  }
  

  if (!django.jsi18n_initialized) {
    django.gettext = function(msgid) {
      var value = django.catalog[msgid];
      if (typeof(value) == 'undefined') {
        return msgid;
      } else {
        return (typeof(value) == 'string') ? value : value[0];
      }
    };

    django.ngettext = function(singular, plural, count) {
      var value = django.catalog[singular];
      if (typeof(value) == 'undefined') {
        return (count == 1) ? singular : plural;
      } else {
        return value[django.pluralidx(count)];
      }
    };

    django.gettext_noop = function(msgid) { return msgid; };

    django.pgettext = function(context, msgid) {
      var value = django.gettext(context + '\x04' + msgid);
      if (value.indexOf('\x04') != -1) {
        value = msgid;
      }
      return value;
    };

    django.npgettext = function(context, singular, plural, count) {
      var value = django.ngettext(context + '\x04' + singular, context + '\x04' + plural, count);
      if (value.indexOf('\x04') != -1) {
        value = django.ngettext(singular, plural, count);
      }
      return value;
    };

    django.interpolate = function(fmt, obj, named) {
      if (named) {
        return fmt.replace(/%\(\w+\)s/g, function(match){return String(obj[match.slice(2,-2)])});
      } else {
        return fmt.replace(/%s/g, function(match){return String(obj.shift())});
      }
    };


    /* formatting library */

    django.formats = {
    "DATETIME_FORMAT": "j. F Y. H:i", 
    "DATETIME_INPUT_FORMATS": [
      "%d.%m.%Y. %H:%M:%S", 
      "%d.%m.%Y. %H:%M:%S.%f", 
      "%d.%m.%Y. %H:%M", 
      "%d.%m.%Y.", 
      "%d.%m.%y. %H:%M:%S", 
      "%d.%m.%y. %H:%M:%S.%f", 
      "%d.%m.%y. %H:%M", 
      "%d.%m.%y.", 
      "%d. %m. %Y. %H:%M:%S", 
      "%d. %m. %Y. %H:%M:%S.%f", 
      "%d. %m. %Y. %H:%M", 
      "%d. %m. %Y.", 
      "%d. %m. %y. %H:%M:%S", 
      "%d. %m. %y. %H:%M:%S.%f", 
      "%d. %m. %y. %H:%M", 
      "%d. %m. %y.", 
      "%Y-%m-%d %H:%M:%S", 
      "%Y-%m-%d %H:%M:%S.%f", 
      "%Y-%m-%d %H:%M", 
      "%Y-%m-%d"
    ], 
    "DATE_FORMAT": "j. F Y.", 
    "DATE_INPUT_FORMATS": [
      "%d.%m.%Y.", 
      "%d.%m.%y.", 
      "%d. %m. %Y.", 
      "%d. %m. %y.", 
      "%Y-%m-%d"
    ], 
    "DECIMAL_SEPARATOR": ",", 
    "FIRST_DAY_OF_WEEK": "1", 
    "MONTH_DAY_FORMAT": "j. F", 
    "NUMBER_GROUPING": "3", 
    "SHORT_DATETIME_FORMAT": "j.m.Y. H:i", 
    "SHORT_DATE_FORMAT": "j.m.Y.", 
    "THOUSAND_SEPARATOR": ".", 
    "TIME_FORMAT": "H:i", 
    "TIME_INPUT_FORMATS": [
      "%H:%M:%S", 
      "%H:%M:%S.%f", 
      "%H:%M"
    ], 
    "YEAR_MONTH_FORMAT": "F Y."
  };

    django.get_format = function(format_type) {
      var value = django.formats[format_type];
      if (typeof(value) == 'undefined') {
        return format_type;
      } else {
        return value;
      }
    };

    /* add to global namespace */
    globals.pluralidx = django.pluralidx;
    globals.gettext = django.gettext;
    globals.ngettext = django.ngettext;
    globals.gettext_noop = django.gettext_noop;
    globals.pgettext = django.pgettext;
    globals.npgettext = django.npgettext;
    globals.interpolate = django.interpolate;
    globals.get_format = django.get_format;

    django.jsi18n_initialized = true;
  }

}(this));

