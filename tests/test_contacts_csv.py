import unittest

from app.contacts.csv_input import CsvInputError, Limits, normalize_phone, suggest_mapping, validate_csv


class ContactsCsvTests(unittest.TestCase):
    def test_canadian_formats_have_one_canonical_identity(self):
        values=['416 555 0123','(416) 555-0123','+1 416 555 0123']
        self.assertEqual({normalize_phone(value) for value in values},{'+14165550123'})
        with self.assertRaises(CsvInputError): normalize_phone('123')
        with self.assertRaises(CsvInputError): normalize_phone('4165550123 ext 25')
        with self.assertRaises(CsvInputError): normalize_phone('4165550123','XX')

    def test_bom_semicolon_mapping_deduplication_and_blank_preservation(self):
        source='\ufeffTéléphone;Prénom;Courriel\n4165550123;Élodie;ELODIE@example.com\n+1 416 555 0123;;\n123;Invalide;bad\n;;\n'.encode()
        result=validate_csv(source,{'phone':'Téléphone','first_name':'Prénom','email':'Courriel'})
        self.assertEqual((result.valid_count,result.invalid_count,result.distinct_count,result.duplicate_count,result.skipped_blank),(2,1,1,1,1))
        self.assertEqual(result.rows[0].profile['display_name'],'Élodie')
        self.assertEqual(result.rows[0].profile['email'],'elodie@example.com')
        self.assertEqual(result.rows[1].profile,{'phone':'+14165550123'})
        self.assertTrue(result.rows[1].duplicate_in_file)
        self.assertEqual(result.rows[2].row_number,4)

    def test_bad_optional_email_does_not_discard_valid_calling_number(self):
        result=validate_csv(b'Phone,Email\n4165550123,invalid\n',{'phone':'Phone','email':'Email'})
        self.assertEqual(result.valid_count,1)
        self.assertNotIn('email',result.rows[0].profile)
        self.assertIn('Courriel invalide',result.rows[0].warnings[0])

    def test_derived_name_respects_the_profile_boundary(self):
        source=('Phone,First,Last\n4165550123,'+'a'*120+','+'b'*120+'\n').encode()
        result=validate_csv(source,{'phone':'Phone','first_name':'First','last_name':'Last'},delimiter=',')
        self.assertEqual(result.valid_count,1)
        self.assertNotIn('display_name',result.rows[0].profile)
        self.assertEqual(len(result.rows[0].profile['first_name']),120)
        self.assertTrue(result.rows[0].warnings)

    def test_ambiguous_or_privilege_mapping_is_rejected(self):
        self.assertNotIn('phone',suggest_mapping(('Phone','Téléphone','Prénom')))
        self.assertEqual(suggest_mapping(('Téléphone','Prénom')),{'phone':'Téléphone','first_name':'Prénom'})
        for source,mapping in [(b'Phone,phone\n4165550123,4165550123',{'phone':'Phone'}),
                               (b'Phone,Nom\n4165550123,A',{'phone':'Phone','do_not_contact':'Nom'}),
                               (b'Phone,Nom\n4165550123,A',{'phone':'missing'}),
                               (b'Phone,Nom\n4165550123,A',{'phone':'Phone','first_name':'Phone'})]:
            with self.subTest(mapping=mapping),self.assertRaises(CsvInputError): validate_csv(source,mapping,delimiter=',')

    def test_bounds_and_explicit_encoding(self):
        source='Téléphone;Nom\n4165550123;Élodie\n'.encode('cp1252')
        with self.assertRaises(CsvInputError): validate_csv(source,{'phone':'Téléphone'},delimiter=';')
        result=validate_csv(source,{'phone':'Téléphone','first_name':'Nom'},encoding='cp1252',delimiter=';')
        self.assertEqual(result.rows[0].profile['first_name'],'Élodie')
        with self.assertRaises(CsvInputError): validate_csv(source,{'phone':'Téléphone'},limits=Limits(max_bytes=2))
        with self.assertRaises(CsvInputError): validate_csv(b'Phone\n4165550123\n4165550124',{'phone':'Phone'},limits=Limits(max_rows=1))
        with self.assertRaises(CsvInputError): validate_csv(b'Phone\n\x00',{'phone':'Phone'})
        with self.assertRaises(CsvInputError): validate_csv(b'Phone\n',{'phone':'Phone'})

    def test_quotes_and_malformed_rows_remain_explainable(self):
        result=validate_csv(b'Phone,Name\n4165550123,"Hello, world"\n4165550124\n',{'phone':'Phone','display_name':'Name'},delimiter=',')
        self.assertEqual(result.rows[0].profile['display_name'],'Hello, world')
        self.assertEqual(result.invalid_count,1)
        with self.assertRaises(CsvInputError): validate_csv(b'Phone,Name\n4165550123,"unterminated',{'phone':'Phone'},delimiter=',')
