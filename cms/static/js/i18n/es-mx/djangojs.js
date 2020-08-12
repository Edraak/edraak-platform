

(function(globals) {

  var django = globals.django || (globals.django = {});

  
  django.pluralidx = function(n) {
    var v=(n != 1);
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
      "%(sel)s de %(cnt)s seleccionado/a", 
      "%(sel)s de %(cnt)s seleccionados/as"
    ], 
    "6 a.m.": "6 a.m.", 
    "Available %s": "Disponible %s", 
    "Cancel": "Cancelar", 
    "Choose": "Seleccionar", 
    "Choose a time": "Elija una hora", 
    "Choose all": "Seleccionar todos", 
    "Chosen %s": "%s seleccionados", 
    "Click to choose all %s at once.": "Da click para seleccionar todos los %s de una vez.", 
    "Click to remove all chosen %s at once.": "Da click para eliminar todos los %s seleccionados de una vez.", 
    "Filter": "Filtro", 
    "Hide": "Ocultar", 
    "Midnight": "Medianoche", 
    "Noon": "Mediod\u00eda", 
    "Now": "Ahora", 
    "Remove": "Quitar", 
    "Remove all": "Eliminar todos", 
    "Show": "Mostrar", 
    "This is the list of available %s. You may choose some by selecting them in the box below and then clicking the \"Choose\" arrow between the two boxes.": "Esta es la lista de los %s disponibles. Usted puede elegir algunos seleccion\u00e1ndolos en el cuadro de abajo y haciendo click en la flecha \"Seleccionar\" entre las dos cajas.", 
    "This is the list of chosen %s. You may remove some by selecting them in the box below and then clicking the \"Remove\" arrow between the two boxes.": "Esta es la lista de los %s elegidos. Usted puede eliminar algunos seleccion\u00e1ndolos en el cuadro de abajo y haciendo click en la flecha \"Eliminar\" entre las dos cajas.", 
    "Today": "Hoy", 
    "Tomorrow": "Ma\u00f1ana", 
    "Type into this box to filter down the list of available %s.": "Escriba en esta casilla para filtrar la lista de %s disponibles.", 
    "Yesterday": "Ayer", 
    "You have selected an action, and you haven't made any changes on individual fields. You're probably looking for the Go button rather than the Save button.": "Ha seleccionado una acci\u00f3n pero no ha realizado ninguna modificaci\u00f3n en campos individuales. Es probable que lo que necesite usar en realidad sea el bot\u00f3n Ejecutar y no el bot\u00f3n Guardar.", 
    "You have selected an action, but you haven't saved your changes to individual fields yet. Please click OK to save. You'll need to re-run the action.": "Ha seleccionado una acci\u00f3n, pero todav\u00eda no ha grabado las modificaciones que ha realizado en campos individuales. Por favor haga click en Aceptar para grabarlas. Necesitar\u00e1 ejecutar la acci\u00f3n nuevamente.", 
    "You have unsaved changes on individual editable fields. If you run an action, your unsaved changes will be lost.": "Tiene modificaciones sin guardar en campos modificables individuales. Si ejecuta una acci\u00f3n las mismas se perder\u00e1n."
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
    "DATETIME_FORMAT": "j \\d\\e F \\d\\e Y \\a \\l\\a\\s H:i", 
    "DATETIME_INPUT_FORMATS": [
      "%d/%m/%Y %H:%M:%S", 
      "%d/%m/%Y %H:%M:%S.%f", 
      "%d/%m/%Y %H:%M", 
      "%d/%m/%y %H:%M:%S", 
      "%d/%m/%y %H:%M:%S.%f", 
      "%d/%m/%y %H:%M", 
      "%Y-%m-%d %H:%M:%S", 
      "%Y-%m-%d %H:%M:%S.%f", 
      "%Y-%m-%d %H:%M", 
      "%Y-%m-%d"
    ], 
    "DATE_FORMAT": "j \\d\\e F \\d\\e Y", 
    "DATE_INPUT_FORMATS": [
      "%d/%m/%Y", 
      "%d/%m/%y", 
      "%Y%m%d", 
      "%Y-%m-%d"
    ], 
    "DECIMAL_SEPARATOR": ".", 
    "FIRST_DAY_OF_WEEK": "1", 
    "MONTH_DAY_FORMAT": "j \\d\\e F", 
    "NUMBER_GROUPING": "3", 
    "SHORT_DATETIME_FORMAT": "d/m/Y H:i", 
    "SHORT_DATE_FORMAT": "d/m/Y", 
    "THOUSAND_SEPARATOR": "\u00a0", 
    "TIME_FORMAT": "H:i", 
    "TIME_INPUT_FORMATS": [
      "%H:%M:%S", 
      "%H:%M:%S.%f", 
      "%H:%M"
    ], 
    "YEAR_MONTH_FORMAT": "F \\d\\e Y"
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

