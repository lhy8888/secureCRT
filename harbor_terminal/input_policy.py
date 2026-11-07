"""Validated per-session input transformations and pacing, without I/O."""
from dataclasses import dataclass


DEFAULT_INPUT = dict(send_char_delay_ms='0',send_line_delay_ms='0',paste_newline='auto',
    paste_quote='none',alt_meta='escape',remote_clear_history='allow')
INPUT_FIELDS=frozenset(DEFAULT_INPUT)


@dataclass(frozen=True)
class InputPolicy:
    values: dict

    @classmethod
    def parse(cls,values=None):
        if values is None:values={}
        if not isinstance(values,dict) or set(values)-INPUT_FIELDS:raise ValueError('Unknown input policy field')
        result=dict(DEFAULT_INPUT,**values)
        for key,maximum in (('send_char_delay_ms',1000),('send_line_delay_ms',30000)):
            value=result[key]
            if not isinstance(value,str) or not value.isascii() or not value.isdigit() or len(value)>8 or int(value)>maximum:
                raise ValueError('Invalid send delay')
        for key,allowed in dict(paste_newline=('auto','keep','cr','lf','crlf'),paste_quote=('none','posix','powershell'),
                                alt_meta=('escape','text'),remote_clear_history=('allow','preserve')).items():
            if result[key] not in allowed:raise ValueError('Invalid input policy')
        return cls(result)

    def chunks(self,data):
        """Delay applies after each byte/line; a CRLF pair is one line ending."""
        character=int(self.values['send_char_delay_ms'])/1000
        line=int(self.values['send_line_delay_ms'])/1000
        if not character and not line:
            yield data,0;return
        start=0
        for index,byte in enumerate(data):
            newline=byte==10 or byte==13 and (index+1==len(data) or data[index+1]!=10)
            if character or newline:
                yield data[start:index+1],character+(line if newline else 0)
                start=index+1
        if start<len(data):yield data[start:],0


def convert_newlines(text,style):
    if style=='keep':return text
    if style not in ('cr','lf','crlf'):raise ValueError('Unknown newline style')
    return text.replace('\r\n','\n').replace('\r','\n').replace('\n',dict(cr='\r',lf='\n',crlf='\r\n')[style])


def quote_text(text,style):
    if style=='none':return text
    if style=='posix':return "'"+text.replace("'","'\"'\"'")+"'"
    if style=='powershell':return "'"+text.replace("'","''")+"'"
    raise ValueError('Unknown quoting style')
