"""Explicit, live UI bindings. Never translates arbitrary user/provider text."""
import json
import os
from pathlib import Path
import weakref

_catalogs={}
_locale='pt-BR'
_settings=None
_bindings=[]
_listeners=[]


def normalize(value):return 'en-US' if value=='en-US' else 'pt-BR'


def directory():return Path(os.environ.get('ORBITZ_I18N_DIR',Path(__file__).parent))


def _load():
    if not _catalogs:
        for locale in ('pt-BR','en-US'):
            try:_catalogs[locale]=json.loads((directory()/(locale+'.json')).read_text(encoding='utf-8'))
            except (OSError,ValueError):_catalogs[locale]={}
    return _catalogs


def tr(key,values=None,**kwargs):
    catalogs=_load();template=catalogs.get(_locale,{}).get(key,catalogs['pt-BR'].get(key,key))
    fields=dict(values or {},**kwargs)
    class Safe(dict):
        def __missing__(self,key):return '{'+key+'}'
    return template.format_map(Safe(fields))


class Message:
    def __init__(self,key,**values):self.key,self.values=key,values
    def render(self):return tr(self.key,self.values)


def msg(key,**values):return Message(key,**values)


def _text(value):return value.render() if isinstance(value,Message) else value


def _slot(property):
    return '@content' if property in ('text','label','markup','set_text','set_label','set_markup') else property


def _bind(owner,property,value,method=False,args=()):
    _bindings[:]=[item for item in _bindings if item[0]() is not None and not(item[0]() is owner and _slot(item[1])==_slot(property))]
    if isinstance(value,Message):_bindings.append((weakref.ref(owner),property,value,method,args))


def set(owner,property,value):
    _bind(owner,property,value)
    owner.set_property(property.replace('_','-'),_text(value))
    return owner


def call(owner,method,value,*args):
    _bind(owner,method,value,True,args)
    getattr(owner,method)(_text(value),*args)
    return owner


def widget(constructor,*args,**properties):
    owner=constructor(*args,**{key:_text(value) for key,value in properties.items()})
    for key,value in properties.items():_bind(owner,key,value)
    return owner


def refresh(locale):
    global _locale
    _locale=normalize(locale)
    for item in list(_bindings):
        reference,property,value,method,args=item;owner=reference()
        if owner is None:_bindings.remove(item);continue
        try:
            if method:getattr(owner,property)(value.render(),*args)
            else:owner.set_property(property.replace('_','-'),value.render())
        except (RuntimeError,TypeError):_bindings.remove(item)
    for reference in list(_listeners):
        callback=reference()
        if callback is None:_listeners.remove(reference)
        else:callback(_locale)


def watch(callback):
    reference=weakref.WeakMethod(callback) if getattr(callback,'__self__',None) is not None else weakref.ref(callback)
    _listeners.append(reference)
    return lambda:_listeners.remove(reference) if reference in _listeners else None


def get_locale():return _locale


def configure():
    global _settings
    if _settings is not None:return
    refresh(os.environ.get('ORBITZ_LOCALE','pt-BR'))
    if os.environ.get('ORBITZ_LOCALE'):
        return
    try:
        import gi
        from gi.repository import Gio
        source=Gio.SettingsSchemaSource.get_default()
        schema=source.lookup('io.orbitz.Postits',True) if source else None
        if schema and schema.has_key('ui-language'):
            _settings=Gio.Settings.new_full(schema,None,None)
            refresh(_settings.get_string('ui-language'))
            _settings.connect('changed::ui-language',lambda settings,key:refresh(settings.get_string(key)))
    except (ImportError,ValueError,RuntimeError):pass


configure()


def buttons(dialog,*args):
    for index in range(0,len(args),2):
        button(dialog,args[index],args[index+1])


def button(dialog,label,response):
    owner=dialog.add_button(_text(label),response)
    _bind(owner,'label',label)
    return owner


class Composite(Message):
    def __init__(self,parts):self.parts=parts
    def render(self):return ''.join(str(_text(value)) for value in self.parts)


def join(separator,values):
    parts=[]
    for index,value in enumerate(values):
        if index:parts.append(separator)
        parts.append(value)
    return Composite(parts)


Message.__str__=lambda self:self.render()
Message.__format__=lambda self,spec:format(self.render(),spec)
Message.__add__=lambda self,other:Composite([self,other])
Message.__radd__=lambda self,other:Composite([other,self])


def combo_append(combo,identity,label):
    combo.append(identity,_text(label))
    if isinstance(label,Message):
        class RowLabel(Message):
            def render(self):return label.render()
        reference=weakref.ref(combo)
        def refresh_row(locale):
            target=reference()
            if target is None:return
            model=target.get_model();iterator=model.get_iter_first()
            while iterator is not None:
                if model.get_value(iterator,1)==identity:
                    target._orbitz_language_updating=True
                    try:model.set_value(iterator,0,label.render())
                    finally:target._orbitz_language_updating=False
                    break
                iterator=model.iter_next(iterator)
        # The widget owns its callback; the global listener only holds a weak ref.
        callbacks=getattr(combo,'_orbitz_language_callbacks',[]);callbacks.append(refresh_row)
        combo._orbitz_language_callbacks=callbacks;watch(refresh_row)


def stack_page(stack,child,identity,title):
    stack.add_titled(child,identity,_text(title))
    if isinstance(title,Message):
        reference=weakref.ref(stack);child_reference=weakref.ref(child)
        def refresh_title(locale):
            parent=reference();page=child_reference()
            if parent is not None and page is not None:parent.child_set_property(page,'title',title.render())
        callbacks=getattr(child,'_orbitz_language_callbacks',[]);callbacks.append(refresh_title)
        child._orbitz_language_callbacks=callbacks;watch(refresh_title)


class LocalDate(Message):
    """Display date only; persisted dates and editable ISO fields never change."""
    def __init__(self,value,kind):self.value,self.kind=value,kind
    def render(self):
        from datetime import date,datetime
        value=self.value
        if isinstance(value,str):value=datetime.fromisoformat(value[:-1]+'+00:00' if value.endswith('Z') else value) if 'T' in value or ' ' in value else date.fromisoformat(value)
        pattern='%m/%d' if get_locale()=='en-US' else '%d/%m'
        if self.kind in ('date','datetime'):pattern+='/%Y'
        if self.kind in ('datetime','short_datetime'):pattern+=' %H:%M'
        return value.strftime(pattern)


def date_text(value,kind='date'):return LocalDate(value,kind)


class TransformedMessage(Message):
    def __init__(self,value,method,args):self.value,self.method,self.args=value,method,args
    def render(self):return getattr(str(_text(self.value)),self.method)(*self.args)


def transform(value,method,*args):return TransformedMessage(value,method,args)


def mnemonic_label(Gtk,value):
    owner=Gtk.Label.new_with_mnemonic(_text(value))
    _bind(owner,'set_label',value,True)
    return owner


def tree_column(Gtk,title,renderer,**attributes):
    owner=Gtk.TreeViewColumn(_text(title),renderer,**attributes)
    _bind(owner,'title',title)
    return owner


def model_append(model,values,parent=None,tree=False,owner=None):
    """Keep translated model cells tied to stable GTK row references."""
    plain=[_text(value) for value in values]
    iterator=model.append(parent,plain) if tree else model.append(plain)
    messages={index:value for index,value in enumerate(values) if isinstance(value,Message)}
    if not messages:return iterator
    from gi.repository import Gtk
    reference=Gtk.TreeRowReference.new(model,model.get_path(iterator))
    if owner is None:raise ValueError('A translated model needs its view owner')
    if not hasattr(owner,'_orbitz_language_model_callback'):
        owner._orbitz_language_rows=[]
        weak=weakref.ref(owner)
        weak_model=weakref.ref(model)
        def refresh_rows(locale):
            target=weak()
            current_model=weak_model()
            if target is None or current_model is None:return
            rows=[]
            for row,labels in target._orbitz_language_rows:
                if not row.valid():continue
                current=current_model.get_iter(row.get_path())
                for column,message in labels.items():current_model.set_value(current,column,message.render())
                rows.append((row,labels))
            target._orbitz_language_rows=rows
        owner._orbitz_language_model_callback=refresh_rows
        watch(refresh_rows)
    owner._orbitz_language_rows.append((reference,messages))
    return iterator



def model_clear(model,owner):
    owner._orbitz_language_rows=[]
    model.clear()


# Compatibility is explicit and limited to known Orbitz warning fields, never user text.
def known_message(value,keys):
    if not isinstance(value,str):return value
    catalogs=_load()
    for key in keys:
        if any(catalog.get(key)==value for catalog in catalogs.values()):return msg(key)
    return value


def known_lines(value,keys):
    import re
    return Composite([known_message(part,keys) for part in re.split(r'(\r?\n)',value)]) if isinstance(value,str) else value


def exception(error_type,key,values=None,**kwargs):
    """Keep public exception classes/args unchanged; carry explicit UI provenance."""
    descriptor=msg(key,**dict(values or {},**kwargs))
    error=error_type(descriptor.render())
    error.orbitz_message=descriptor
    return error


def error_message(error,limit=None):
    value=getattr(error,'orbitz_message',None)
    if not isinstance(value,Message):value=str(error)
    return transform(value,'__getitem__',slice(0,limit)) if limit is not None else value
