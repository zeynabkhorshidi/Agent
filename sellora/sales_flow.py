"""Deterministic sales dialogue shared by text, final STT and future telephone channel."""
import re
from .domain import normalize,find_products,quantity,search_text

ORDINALS={'اولی':0,'اول':0,'دومی':1,'دوم':1,'سومی':2,'سوم':2}

def prompt_options(state,products):
    flavors=list(dict.fromkeys(p.get('flavor','') for p in products if p.get('flavor')))
    if len(flavors)>1:
        options=[{'label':f,'skus':[p['sku'] for p in products if p.get('flavor')==f]} for f in flavors]
        kind='flavor';question='کدام طعم را می‌خواهید؟'
    else:
        options=[{'label':p['name'],'skus':[p['sku']]} for p in products]
        kind='sku';question='کدام محصول را انتخاب می‌کنید؟'
    state['selection']={'kind':kind,'options':options,'offset':0}
    state['choices']=[{'label':o['label'],'text':o['label']} for o in options[:12]]
    labels='، '.join(o['label'] for o in options[:3])
    extra=' گزینه‌های بیشتر را هم می‌توانید ببینید یا بگویید «گزینه‌های بعدی».' if len(options)>3 else ''
    return 'این گزینه‌ها را داریم: '+labels+'. '+question+extra

def selected_product(state,p):
    state['selection']={'kind':'quantity','sku':p['sku']}
    state['choices']=[{'label':f'{n} کارتن','text':f'{n} کارتن'} for n in (1,2,3)]
    return p['name']+' را انتخاب کردید. چند کارتن نیاز دارید؟'

def resolve_selection(state,text,products):
    """Returns (resolved products or None, quantity inferred or None, reply or None)."""
    pending=state.get('selection');by={p['sku']:p for p in products}
    if not pending:return None,None,None
    if pending['kind']=='quantity':
        p=by.get(pending['sku']);n=quantity(text)
        # A newly named product overrides the previous selection.
        found=find_products(text,products)
        if found and (len(found)!=1 or not p or found[0]['sku']!=p['sku']):
            state.pop('selection',None);state['choices']=[];return None,None,None
        if n is None:return None,None,None
        if not p:return None,None,'این کالا دیگر در کاتالوگ نیست. محصول دیگری انتخاب کنید.'
        if 'تا' in text or 'عدد' in text:
            state['selection']={'kind':'unit','sku':p['sku'],'quantity':n}
            state['choices']=[{'label':'بله، کارتن','text':'بله کارتن'},{'label':'انتخاب دوباره','text':'انتخاب دوباره'}]
            return None,None,f'منظورتان {n} کارتن {p["name"]} است؟'
        return [p],n,None
    if pending['kind']=='unit':
        if search_text(text) in ('بله','بله کارتن','کارتن','تایید','تأیید'):
            p=by.get(pending['sku'])
            return ([p],pending['quantity'],None) if p else (None,None,'کالا دیگر در کاتالوگ نیست.')
        state.pop('selection',None);state['choices']=[];return None,None,None
    options=pending['options'];offset=pending.get('offset',0)
    if 'گزینه' in text and ('بعدی' in text or 'بیشتر' in text):
        offset=(offset+3)%len(options);pending['offset']=offset
        state['choices']=[{'label':o['label'],'text':o['label']} for o in options[offset:offset+12]]
        return None,None,'گزینه‌های بعدی: '+'، '.join(o['label'] for o in options[offset:offset+3])+'. کدام را می‌خواهید؟'
    chosen=None
    for word,index in ORDINALS.items():
        if re.search(r'\b'+word+r'\b',text) and offset+index<len(options):chosen=options[offset+index];break
    cleaned=search_text(text)
    if not chosen:
        matches=[o for o in options if search_text(o['label']) in cleaned or cleaned==search_text(o['label'])]
        if len(matches)==1:chosen=matches[0]
    if chosen:
        selected=[by[sku] for sku in chosen['skus'] if sku in by]
        state.pop('selection',None);state['choices']=[]
        return selected,quantity(text) if quantity(text) is not None else pending.get('quantity'),None
    return None,None,None
