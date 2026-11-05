"""Native Excel files with numeric measures and explicitly textual user data."""
from datetime import date, datetime, timezone
from io import BytesIO
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.utils import get_column_letter

COLUMNS=[('calls','Appels lancés'),('answered','Décrochés'),('answer_rate','Taux de décroché (%)'),
 ('contacts','Contacts distincts'),('manual','Manuels'),('automatic','Automatiques'),('no_answer','Sans réponse'),
 ('busy','Occupés'),('failed','Échecs'),('cancelled','Annulés'),('in_progress','En cours'),
 ('bookings','RDV créés'),('cancelled_bookings','RDV annulés (statut actuel)'),('bookings_per_100_calls','RDV / 100 appels'),
 ('pauses','Pauses enregistrées'),('stops','Arrêts enregistrés'),('starts','Démarrages / reprises'),
 ('automatic_pauses','Pauses automatiques identifiées'),('talk_seconds','Conversation connue (secondes)'),
 ('average_talk_seconds','Durée moyenne connue (secondes)'),('duration_known','Appels avec durée connue'),('duration_missing','Décrochés sans durée connue')]


def workbook(report):
    book=Workbook(write_only=True)
    book.properties.creator='Unlimited Talks'
    book.properties.title='Activité des agents'
    def sheet(name,headers,rows):
        ws=book.create_sheet(name);ws.freeze_panes='A2'
        for i,header in enumerate(headers,1):
            ws.column_dimensions[get_column_letter(i)].width=min(40,max(19,len(header)+2))
        def cells(values,heading=False):
            output=[]
            for value in values:
                if isinstance(value,datetime):value=value.astimezone(timezone.utc).isoformat()
                cell=WriteOnlyCell(ws,value=ILLEGAL_CHARACTERS_RE.sub('',value)[:32767] if isinstance(value,str) else value)
                if isinstance(value,str):cell.data_type='s'  # Never a formula or a user-supplied link.
                if heading:
                    cell.fill=PatternFill('solid',fgColor='173F65');cell.font=Font(color='FFFFFF',bold=True)
                    cell.alignment=Alignment(wrap_text=True,vertical='center')
                output.append(cell)
            return output
        ws.append(cells(headers,True));count=1
        for row in rows:ws.append(cells(row));count+=1
        ws.auto_filter.ref=f'A1:{get_column_letter(len(headers))}{count}'
    agents={str(agent['id']):agent for agent in report['agents']}
    def identity(identifier):
        row=agents[str(identifier)];return [row['display_name'],row['email']]
    def values(metrics):return [metrics.get(key) for key,_ in COLUMNS]
    columns=[label for _,label in COLUMNS]
    sheet('Synthèse',['Agent','Courriel',*columns],(identity(a['id'])+values(a['metrics']) for a in report['agents']))
    sheet('Par jour',['Agent','Courriel','Date',*columns,'Premier appel (UTC)','Dernier appel (UTC)'],
        (identity(day['agent_id'])+[date.fromisoformat(day['date']),*values(day),day['first_call_at'],day['last_call_at']] for day in report['daily']))
    if report['hourly']:
        agent=report['agents'][0]
        sheet('Par heure',['Agent','Date','Heure locale','Décalage UTC','Début heure (UTC)',*columns],
            ([agent['display_name'],date.fromisoformat(hour['date']),hour['label'],hour['utc_offset'],hour['starts_at'],*values(hour)] for hour in report['hourly']))
    sheet('Repères',['Indicateur','Définition'],[
        ['Début',str(report['period']['start'])],['Fin incluse',str(report['period']['end'])],
        ['Fuseau horaire',report['period']['timezone']],['Extraction (UTC)',report['generated_at'].isoformat()],
        ['Jours sans activité','Les lignes à zéro sont incluses. Une absence d’activité enregistrée ne prouve pas une absence au travail.'],
        *[[{'calls':'Appels lancés','answered':'Décrochés','talk':'Durées de conversation','bookings':'Rendez-vous','pauses':'Pauses et arrêts','time':'Temps et fuseaux'}.get(key,key),value] for key,value in report['definitions'].items()],
        ['RDV / 100 appels','RDV créés sur la période / appels lancés sur la période × 100. Les RDV ne sont pas forcément issus des appels de cette même période.'],
        ['Durée moyenne connue','Somme des durées connues / nombre de décrochés disposant d’une durée. Les durées inconnues sont exclues.']])
    target=BytesIO();book.save(target)
    return target.getvalue()
