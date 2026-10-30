"""Small Telegram Bot API long-polling transport with timeouts and redacted failures."""
from __future__ import annotations
import json,time
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

class TelegramAPIError(RuntimeError): pass
class TelegramDeliveryUncertain(TelegramAPIError): pass

class TelegramAPI:
    def __init__(self,token:str,request_fn=None):
        if not token or any(c.isspace() for c in token): raise ValueError('A bot token is required')
        self._url=f'https://api.telegram.org/bot{token}/'
        self._request_fn=request_fn or self._request
    def _request(self,method,params,timeout):
        request=Request(self._url+method,data=json.dumps(params).encode(),headers={'Content-Type':'application/json'})
        try:
            with urlopen(request,timeout=timeout) as response:return json.loads(response.read())
        except HTTPError as exc:
            try:body=json.loads(exc.read())
            except Exception:body={}
            if exc.code==429:return body or {'ok':False,'parameters':{'retry_after':1}}
            if method=='sendMessage' and exc.code>=500:raise TelegramDeliveryUncertain('Telegram delivery result is uncertain') from None
            raise TelegramAPIError('Telegram request failed') from None
        except (URLError,TimeoutError,OSError,ValueError):
            error=TelegramDeliveryUncertain if method=='sendMessage' else TelegramAPIError
            raise error('Telegram request failed; delivery may be uncertain' if method=='sendMessage' else 'Telegram request failed') from None
    def call(self,method,params,timeout=15):
        for attempt in range(2):
            result=self._request_fn(method,params,timeout)
            if result.get('ok'):return result.get('result')
            retry=result.get('parameters',{}).get('retry_after')
            if result.get('error_code')==429 and attempt==0 and isinstance(retry,(int,float)):
                time.sleep(min(max(retry,0),30));continue
            if method=='sendMessage' and isinstance(result.get('error_code'),int) and result['error_code']>=500:
                raise TelegramDeliveryUncertain('Telegram delivery result is uncertain')
            raise TelegramAPIError('Telegram API returned an error')
        raise TelegramAPIError('Telegram API rate limit retry exhausted')
    def get_updates(self,offset,timeout=20):
        return self.call('getUpdates',{'offset':offset,'timeout':timeout,'allowed_updates':['message']},timeout=timeout+10) or []
    def get_me(self):
        """Validate the configured bot token without reading updates or sending messages."""
        return self.call('getMe',{})
    def send_message(self,chat_id,text):
        if len(text)>4000:text=text[:3990]+'…'
        return self.call('sendMessage',{'chat_id':chat_id,'text':text},timeout=15)
