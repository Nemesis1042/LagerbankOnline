from crypt import methods
from cv2 import add
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
import sqlite3
import pandas as pd
from database import Database, get_db_connection
import os
import time
import numpy as np
import cv2
import messagebox
import pyzbar
import pygame
from typing import List, Tuple, Callable


app = Flask(__name__)
app.config.from_object('config.Config')
pygame.mixer.init()

def get_users_from_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT Name FROM Teilnehmer ORDER BY Name")
    users = cursor.fetchall()
    conn.close()
    return [user['Name'] for user in users]

def get_products_from_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT Beschreibung FROM Produkt")
    products = cursor.fetchall()
    conn.close()
    return [product['Beschreibung'] for product in products]

def get_db():
    return sqlite3.connect(app.config['SQLALCHEMY_DATABASE_URI'].split('///')[-1])

def submit_purchase(user, product, quantity):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Teilnehmer-ID und Kontostand abrufen
        cursor.execute("SELECT T_ID FROM Teilnehmer WHERE Name = ?", (user,))
        user_row = cursor.fetchone()
        if user_row is None:
            print("Teilnehmer nicht gefunden!")
            return False
        T_ID = user_row['T_ID']
        
        cursor.execute("SELECT Kontostand FROM Konto WHERE T_ID = ?", (T_ID,))
        account_row = cursor.fetchone()
        if account_row is None:
            print("Konto nicht gefunden!")
            return False
        Kontostand = account_row['Kontostand']
        
        # Produktpreis und Produkt-ID abrufen
        cursor.execute("SELECT P_ID, Preis FROM Produkt WHERE Beschreibung = ?", (product,))
        product_row = cursor.fetchone()
        if product_row is None:
            print("Produkt nicht gefunden!")
            return False
        P_ID = product_row['P_ID']
        Preis = product_row['Preis']
        
        # Prüfen, ob genug Guthaben vorhanden ist
        total_price = quantity * Preis
        if total_price > Kontostand:
            print("Nicht genügend Guthaben!")
            return False
        
        # Transaktion einfügen
        cursor.execute("INSERT INTO Transaktion (K_ID, P_ID, Typ, Menge, Datum) VALUES ((SELECT K_ID FROM Konto WHERE T_ID = ?), ?, ?, ?, ?)",
                       (T_ID, P_ID, 'Kauf', quantity, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        # Konto- und Produkt-Updates durchführen
        cursor.execute("UPDATE Konto SET Kontostand = Kontostand - ? WHERE T_ID = ?", (total_price, T_ID))
        cursor.execute("UPDATE Produkt SET Anzahl_verkauft = Anzahl_verkauft + ? WHERE P_ID = ?", (quantity, P_ID))
        
        # Änderungen speichern
        conn.commit()
        print("Transaktion hinzugefügt!")
        return True
    except Exception as e:
        print(f"Fehler beim Hinzufügen der Transaktion: {e}")
        return False
    finally:
        conn.close()

def barcode_scanner():
    cap = cv2.VideoCapture(0)
    barcode_value = None
    while True:
        ret, frame = cap.read()
        if not ret:
            return None

        decoded_objects = pyzbar.decode(frame)
        if decoded_objects:
            barcode_value = decoded_objects[0].data.decode("utf-8")
            if barcode_value == "Brake":
                return None
            return barcode_value

def play_beep():
    pygame.mixer.music.load("pip.wav")
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
    
def add_transaction(db, TN_Barcode, P_Barcode, menge):
    TN_ID = db.execute_select("SELECT T_ID FROM Teilnehmer WHERE TN_Barcode = ?", (TN_Barcode,))
    if not TN_ID:
        raise ValueError("TN_Barcode nicht gefunden!")
    TN_ID = TN_ID[0][0]

    P_ID = db.execute_select("SELECT P_ID FROM Produkt WHERE P_Barcode = ?", (P_Barcode,))
    if not P_ID:
        P_ID = db.execute_select("SELECT P_ID FROM Produkt_plus WHERE P_Barcode = ?", (P_Barcode,))
        if not P_ID:
            raise ValueError("P_Barcode nicht gefunden!")
    P_ID = P_ID[0][0]

    db.execute_update("INSERT INTO Transaktion (K_ID, P_ID, Typ, Menge, Datum) VALUES ((SELECT K_ID FROM Konto WHERE T_ID = ?), ?, 'Kauf', ?,datetime('now', 'localtime'))", (TN_ID, P_ID, menge))

def fetch_users(db: Database) -> List[str]:
    users = [user[0] for user in db.execute_select("SELECT Name FROM Teilnehmer ORDER BY Name")]  # Ruft Benutzernamen aus der Datenbank ab
    return users

def fetch_products(db: Database) -> List[str]:
    products = [product[0] for product in db.execute_select("SELECT Beschreibung FROM Produkt ORDER BY Preis")]  # Ruft Produktbeschreibungen aus der Datenbank ab
    return products

def fetch_p_barcode(db: Database) -> str:
    p_barcode = db.execute_select("SELECT P_Barcode FROM Produkt ") # Ruft den Produktbarcode aus der Datenbank ab
    return p_barcode

def fetch_p_barcode_plus(db: Database) -> str:
    p_barcode_plus = db.execute_select("SELECT Barcode FROM Produkt_Barcode ") # Ruft den Produktbarcode aus der Datenbank ab
    return p_barcode_plus

def fetch_tn_barcode(db: Database) -> str:
    tn_barcode = db.execute_select("SELECT TN_Barcode FROM Teilnehmer ")  # Ruft den Benutzerbarcode aus der Datenbank ab
    return tn_barcode
    
def fetch_transactions(db: Database, user_id: int) -> List[Tuple]:
    transactions = db.execute_select("SELECT * FROM Transaktion WHERE K_ID = ? ORDER BY Datum DESC", (user_id,))  # Ruft Transaktionen für einen bestimmten Benutzer ab
    return transactions

@app.route('/update_product_dropdowns', methods=['GET'])
def update_product_dropdowns_route():
    db = Database()
    products = fetch_products(db)  # Ruft Produktbeschreibungen ab
    return jsonify({'products': products})
    

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scan', methods=['POST'])
def scan():
    file = request.files['image'].read()
    npimg = np.fromstring(file, np.uint8)
    img = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
    
    barcodes = pyzbar.decode(img)
    barcode_data = []
    for barcode in barcodes:
        barcode_info = barcode.data.decode('utf-8')
        barcode_data.append(barcode_info)
    
    return jsonify({'barcodes': barcode_data})

@app.route('/add_buy', methods=['GET', 'POST'])
def add_buy():
    if request.method == 'POST':
        user = request.form['user']
        product = request.form['product']
        quantity = int(request.form['quantity'])
        success = submit_purchase(user, product, quantity)
        if success:
            flash('Purchase added successfully', 'success')
        else:
            flash('Error adding purchase', 'danger')
        return redirect(url_for('add_buy'))
    users = get_users_from_db()
    products = get_products_from_db()
    return render_template('add_buy.html', users=users, products=products)

@app.route('/submit_buy', methods=['POST'])
def submit_buy():
    user = request.form['user']
    product = request.form['product']
    quantity = int(request.form['quantity'])
    success = submit_purchase(user, product, quantity)
    if success:
        flash('Purchase submitted successfully', 'success')
    else:
        flash('Error submitting purchase', 'danger')
    return redirect(url_for('add_buy'))

@app.route('/watch')
def watch():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Produkt';")
    if not cursor.fetchone():
        conn.close()
        return "Die Tabelle 'Produkt' existiert nicht in der Datenbank.", 404
    produkt_infos = cursor.execute("SELECT P_ID, Beschreibung, ROUND(Preis, 2) as Preis FROM Produkt").fetchall()
    produkt_summen = ", ".join([f"SUM(CASE WHEN Transaktion.P_ID = {pid} THEN Transaktion.Menge ELSE 0 END) AS '{desc} ({preis:.2f}€)'" for pid, desc, preis in produkt_infos])
    sql_query = f"""
        SELECT 
            Teilnehmer.Name,
            Konto.Einzahlung AS Einzahlung_€,
            printf('%04.2f', ROUND(Konto.Kontostand, 2)) AS Kontostand_€,
            {produkt_summen}
        FROM Teilnehmer 
        JOIN Konto ON Teilnehmer.T_ID = Konto.T_ID
        LEFT JOIN Transaktion ON Konto.K_ID = Transaktion.K_ID
        GROUP BY Teilnehmer.T_ID, Teilnehmer.Name, Konto.Einzahlung, ROUND(Konto.Kontostand, 2)
        ORDER BY Teilnehmer.Name;
    """
    result = cursor.execute(sql_query).fetchall()
    conn.close()
    df = pd.DataFrame(result, columns=[desc[0] for desc in cursor.description])
    return render_template('watch.html', tables=df.to_html(classes='data', header="true", index=False))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form['password']
        if password == '1':
            return redirect(url_for('admin'))
        else:
            flash('Invalid password, try again.', 'danger')
    return render_template('login.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/add_user', methods=['GET', 'POST'])
def add_user():
    if request.method == 'POST':
        user = request.form['user']
        amount = float(request.form['amount'])
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT Name FROM Teilnehmer WHERE Name = ?", (user,))
        if cur.fetchone():
            flash('User already exists!', 'danger')
        else:
            cur.execute("INSERT INTO Teilnehmer (Name) VALUES (?)", (user,))
            t_id = cur.execute("SELECT T_ID FROM Teilnehmer WHERE Name = ?", (user,)).fetchone()[0]
            cur.execute("INSERT INTO Konto (Einzahlung, Kontostand, Eröffnungsdatum, T_ID) VALUES (?, ?, ?, ?)",
                        (amount, amount, datetime.now().strftime("%d.%m.%Y"), t_id))
            cur.execute("INSERT INTO Transaktion (K_ID, P_ID, Typ, Menge, Datum) VALUES (?, ?, ?, ?, ?)", (t_id, 0, 'Einzahlung', amount, datetime.now().strftime("%d.%m.%Y %H:%M:%S")))
            conn.commit()
            flash('User added successfully.', 'success')
        conn.close()
        return redirect(url_for('admin'))
    return render_template('add_user.html')

@app.route('/add_fund', methods=['GET', 'POST'])
def add_fund():
    if request.method == 'POST':
        user = request.form['user']
        amount = float(request.form['amount'])
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT Name FROM Teilnehmer WHERE Name = ?", (user,))
        if not cur.fetchone():
            flash('User not found!', 'danger')
        else:
            
            user_balance = cur.execute("SELECT Kontostand FROM Konto JOIN Teilnehmer ON Konto.T_ID = Teilnehmer.T_ID WHERE Teilnehmer.Name = ?", (user,)).fetchone()
            if user_balance:
                new_balance = user_balance['Kontostand'] + amount
                cur.execute("UPDATE Konto SET Kontostand = ? WHERE T_ID = (SELECT T_ID FROM Teilnehmer WHERE Name = ?)", (new_balance, user))
                cur.execute("INSERT INTO Transaktion (K_ID, P_ID, Typ, Menge, Datum) VALUES ((SELECT T_ID FROM Teilnehmer WHERE Name = ?), 0, 'Einzahlung', ?, ?)", (user, amount, datetime.now().strftime("%d.%m.%Y %H:%M:%S")))
                conn.commit()
                flash(f'{amount} € successfully added.', 'success')
            else:
                flash('User has no account balance!', 'danger')
        conn.close()
        return redirect(url_for('admin'))
    else:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT Name FROM Teilnehmer")
        users = [row[0] for row in cur.fetchall()]
        conn.close()
        return render_template('add_fund.html', users=users)

@app.route('/withdraw_fund', methods=['GET', 'POST'])
def withdraw_fund():
    if request.method == 'POST':
        user = request.form['user']
        amount = float(request.form['amount'])
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT Name FROM Teilnehmer WHERE Name = ?", (user,))
        if not cur.fetchone():
            flash('User not found!', 'danger')
        else:
            current_balance = cur.execute("SELECT Kontostand FROM Konto JOIN Teilnehmer ON Konto.T_ID = Teilnehmer.T_ID WHERE Teilnehmer.Name = ?", (user,)).fetchone()
            current_balance = current_balance['Kontostand'] if current_balance else 0
            user_balance = cur.execute("SELECT Kontostand FROM Konto JOIN Teilnehmer ON Konto.T_ID = Teilnehmer.T_ID WHERE Teilnehmer.Name = ?", (user,)).fetchone()
            if user_balance:
                if amount > user_balance['Kontostand']:
                    flash('Insufficient balance!', 'danger')
                else:
                    new_balance = user_balance['Kontostand'] - amount
                    cur.execute("UPDATE Konto SET Kontostand = ? WHERE T_ID = (SELECT T_ID FROM Teilnehmer WHERE Name = ?)", (new_balance, user))
                    cur.execute("INSERT INTO Transaktion (K_ID, P_ID, Typ, Menge, Datum) VALUES ((SELECT T_ID FROM Teilnehmer WHERE Name = ?), 0, 'Auszahlung', ?, ?)", (user, amount, datetime.now().strftime("%d.%m.%Y %H:%M:%S")))
                    conn.commit()
                    flash(f'{amount} € successfully withdrawn.', 'success')
            else:
                flash('User has no account balance!', 'danger')
        conn.close()
        return redirect(url_for('admin'))
    else:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT Name FROM Teilnehmer")
        users = [row[0] for row in cur.fetchall()]
        conn.close()
        return render_template('withdraw_fund.html', users=users)

@app.route('/edit_user', methods=['GET', 'POST'])
def edit_user():
    if request.method == 'POST':
        selected_user = request.form.get('selected_user')
        action = request.form.get('action')
        conn = get_db_connection()
        cur = conn.cursor()
        if action == 'update':
            new_name = request.form.get('new_name')
            if not selected_user or not new_name:
                flash('Please fill out all fields.', 'danger')
                return redirect(url_for('edit_user'))
            try:
                cur.execute("UPDATE Teilnehmer SET Name = ? WHERE Name = ?", (new_name, selected_user))
                conn.commit()
                flash('Username successfully updated.', 'success')
            except Exception as e:
                flash(f'Error updating username: {e}', 'danger')
        elif action == 'delete':
            if not selected_user:
                flash('Please select a user.', 'danger')
                return redirect(url_for('edit_user'))
            try:
                cur.execute("DELETE FROM Konto WHERE T_ID = (SELECT T_ID FROM Teilnehmer WHERE Name = ?)", (selected_user,))
                cur.execute("DELETE FROM Teilnehmer WHERE Name = ?", (selected_user,))
                conn.commit()
                flash('User successfully deleted.', 'success')
            except Exception as e:
                flash(f'Error deleting user: {e}', 'danger')
        conn.close()
        return redirect(url_for('edit_user'))
    else:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT Name FROM Teilnehmer")
        users = [row[0] for row in cur.fetchall()]
        conn.close()
        return render_template('edit_user.html', users=users)

@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        product = request.form['product']
        price = float(request.form['price'])
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT Beschreibung FROM Produkt WHERE Beschreibung = ?", (product,))
        if cur.fetchone():
            flash('Product already exists!', 'danger')
        else:
            cur.execute("INSERT INTO Produkt (Beschreibung, Preis, Anzahl_verkauft) VALUES (?, ?, 0)", (product, price))
            conn.commit()
            flash('Product added successfully.', 'success')
        conn.close()
        return redirect(url_for('admin'))
    return render_template('add_product.html')

@app.route('/edit_product_prices', methods=['GET', 'POST'])
def edit_product_prices():
    if request.method == 'POST':
        selected_product = request.form.get('selected_product')
        action = request.form.get('action')
        if action == 'update':
            new_price_str = request.form.get('new_price')
            if new_price_str.strip():
                try:
                    new_price = float(new_price_str)
                except ValueError:
                    flash('Please enter a valid price.', 'danger')
                    return redirect(url_for('edit_product_prices'))
            else:
                new_price = None
            if not selected_product:
                flash('Please select a product.', 'danger')
                return redirect(url_for('edit_product_prices'))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                if new_price is not None:
                    cur.execute("UPDATE Produkt SET Preis = ? WHERE Beschreibung = ?", (new_price, selected_product))
                    conn.commit()
                    flash('Product price successfully updated.', 'success')
            except Exception as e:
                flash(f'Error: {e}', 'danger')
            finally:
                conn.close()
        elif action == 'delete':
            if not selected_product:
                flash('Please select a product.', 'danger')
                return redirect(url_for('edit_product_prices'))
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE Produkt SET Preis = 0.00 WHERE Beschreibung = ?", (selected_product,))
                conn.commit()
                cur.execute("DELETE FROM Produkt WHERE Beschreibung = ?", (selected_product,))
                conn.commit()
                flash('Product successfully deleted.', 'success')
            except Exception as e:
                flash(f'Error: {e}', 'danger')
            finally:
                conn.close()
        else:
            flash('Invalid action.', 'danger')
            return redirect(url_for('edit_product_prices'))
        return redirect(url_for('admin'))
    else:
        products = get_products_from_db()
        return render_template('edit_product_prices.html', products=products)

@app.route('/checkout_tn')
def checkout_tn():
    with Database() as db:
        users = db.execute_select("SELECT Name FROM Teilnehmer ORDER BY Name")
    return render_template('TN-Abfrage.html', users=[user[0] for user in users])

@app.route('/checkout', methods=['POST'])
def checkout():
    benutzer_id = request.form['user']
    if not benutzer_id:
        flash("Please select a participant.", 'danger')
        return redirect(url_for('index'))
    with Database() as db:
        users = db.execute_select("SELECT Name FROM Teilnehmer ORDER BY Name")
        if benutzer_id not in [user[0] for user in users]:
            flash("The selected participant does not exist.", 'danger')
            return redirect(url_for('index'))
        kontostand = db.execute_select("SELECT Kontostand FROM Konto WHERE T_ID = (SELECT T_ID FROM Teilnehmer WHERE Name = ?)", (benutzer_id,))
        geldwerte = kontostand_in_geld(kontostand)
        if geldwerte is None:
            geldwerte = [0] * 11
        return render_template('checkout_c.html', benutzer_id=benutzer_id, kontostand=kontostand[0][0] if kontostand else 0, geldwerte=geldwerte)

def kontostand_in_geld(kontostand):
    if kontostand:
        kontostand_value = kontostand[0][0]
        zwischenstand = round(kontostand_value, 2)
    else:
        kontostand_value = 0
        zwischenstand = 0
    denominations = [20, 10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01]
    counts = []
    for denom in denominations:
        count = zwischenstand // denom
        counts.append(count)
        zwischenstand -= count * denom
    return counts

@app.route('/confirm_checkout', methods=['POST'])
def confirm_checkout():
    benutzer_id = request.form['user']
    with Database() as db:
        db.execute_update("UPDATE Konto SET Kontostand = 0 WHERE T_ID = (SELECT T_ID FROM Teilnehmer WHERE Name = ?)", (benutzer_id,))
        db.execute_update("UPDATE Teilnehmer SET Checkout = 1 WHERE Name = ?", (benutzer_id,))
    flash("Checkout completed.", 'success')
    return redirect(url_for('index'))

@app.route('/kaufstatistik')
def create_kaufstatistik_tab():
    try:
        with Database() as db:
            sql_query = '''SELECT Produkt.Beschreibung, SUM(Transaktion.Menge) AS Anzahl_verkauft
                           FROM Produkt
                           JOIN Transaktion ON Produkt.P_ID = Transaktion.P_ID
                           GROUP BY Produkt.Beschreibung
                           ORDER BY Anzahl_verkauft DESC;'''
            result = db.execute_select(sql_query)
            df = pd.DataFrame(result, columns=[desc[0] for desc in db.cursor.description])
            data = df.to_dict(orient='records')
        return render_template('kaufstatistik.html', data=data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/geld_aufteilen')
def geld_aufteilen():
    conn = get_db_connection()
    kontos = conn.execute("SELECT K_ID, Kontostand FROM Konto").fetchall()
    conn.close()

    denominations = [20, 10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01]
    counts = {denom: 0 for denom in denominations}

    for konto in kontos:
        kontostand = konto['Kontostand']
        zwischenstand = round(kontostand, 2)
        for denom in denominations:
            count = int(zwischenstand // denom)
            counts[denom] += count
            zwischenstand -= count * denom

    sume = sum(denom * count for denom, count in counts.items())
    gesamt_kontostand = sum(konto['Kontostand'] for konto in kontos)
    results = {"counts": counts, "sume": sume, "gesamt_kontostand": gesamt_kontostand}

    return render_template('results.html', results=results)

@app.route('/backup', methods=['GET', 'POST'])
def backup():
    if request.method == 'POST':
        backup_path = request.form.get('backupPath')
        if backup_path:
            try:
                backup_file = os.path.join(backup_path, 'Lagerbank2024_backup.sql')
                with open(backup_file, 'w') as f:
                    conn = sqlite3.connect(app.config['SQLALCHEMY_DATABASE_URI'].split('///')[-1])
                    for line in conn.iterdump():
                        f.write('%s\n' % line)
                    conn.close()
                flash('Database backed up successfully.', 'success')
            except Exception as e:
                flash(f'Error backing up database: {e}', 'danger')
        else:
            flash('Please select a valid backup path.', 'danger')
        return redirect(url_for('backup'))
    return render_template('backup.html')

@app.route('/delete_database', methods=['GET', 'POST'])
def delete_database():
    if request.method == 'POST':
        password = request.form['password']
        if password == 'IchWillDieDatenbankLöschen':
            try:
                conn = get_db_connection()
                with open('database_backup.sql', 'w') as f:
                    for line in conn.iterdump():
                        f.write('%s\n' % line)
                flash('Database backed up successfully.', 'success')
                conn.execute("DROP TABLE IF EXISTS Teilnehmer")
                conn.execute("DROP TABLE IF EXISTS Konto")
                conn.execute("DROP TABLE IF EXISTS Produkt")
                conn.commit()
                flash('Database deleted successfully.', 'success')
            except Exception as e:
                flash(f'Error deleting database: {e}', 'danger')
            return redirect(url_for('delete_database'))
        else:
            flash('Invalid password!', 'danger')
    return render_template('delete_database.html')

def scan_barcode():
    cap = cv2.VideoCapture(0)
    barcode_value = None
    while True:
        ret, frame = cap.read()
        if not ret:
            cap.release()
            cv2.destroyAllWindows()
            return jsonify({"error": "Kamerafehler!"}), 500
        decoded_objects = pyzbar.decode(frame)
        if decoded_objects:
            barcode_value = decoded_objects[0].data.decode("utf-8")
            if barcode_value == "Brake":
                cap.release()
                cv2.destroyAllWindows()
                return jsonify({"error": "Barcode Brake erkannt"}), 400
            cap.release()
            cv2.destroyAllWindows()
            return jsonify({"barcode": barcode_value})
        cv2.imshow("Barcode Scanner", frame)
        key = cv2.waitKey(50)  # 50 ms delay
        if key & 0xFF == ord('q') or key & 0xFF == 27:  # 27 is the ASCII code for ESC
            cap.release()
            cv2.destroyAllWindows()
            return jsonify({"error": "Scan abgebrochen"}), 400

@app.route('/scan_transaction', methods=['POST'])
def scan_transaction():
    db = Database()
    data = request.json
    TN_Barcode = data.get('TN_Barcode')
    if not TN_Barcode:
        return jsonify({"error": "User Barcode fehlt"}), 400

    users_barcode = [barcode[0] for barcode in fetch_tn_barcode(db)]
    if TN_Barcode not in users_barcode:
        return jsonify({"error": "User nicht gefunden!"}), 404

    produk_barcode = set([barcode[0] for barcode in fetch_p_barcode(db)])
    produk_barcode_plus = set([barcode[0] for barcode in fetch_p_barcode_plus(db)])
    produkt_scans = data.get('produkt_scans', [])
    
    for P_Barcode in produkt_scans:
        if P_Barcode not in produk_barcode and P_Barcode not in produk_barcode_plus:
            return jsonify({"error": f"Produkt {P_Barcode} nicht gefunden!"}), 404

        menge = 1
        add_transaction(db, TN_Barcode, P_Barcode, menge)
    
    return jsonify({"message": "Transaktion erfolgreich hinzugefügt!"})

@app.route('/add_transaction', methods=['POST'])
def add_transaction_route():
    db = Database()
    try:
        TN_Barcode = request.form['TN_Barcode']
        P_Barcode = request.form['P_Barcode']
        menge = int(request.form['menge'])
        add_transaction(db, TN_Barcode, P_Barcode, menge)
        return jsonify({'message': 'Transaktion erfolgreich hinzugefügt!'}), 200
    except Exception as e:
        return jsonify({'error': f'Fehler beim Hinzufügen der Transaktion: {e}'}), 500

@app.route('/open_barcode')
def open_barcode():
    return render_template ('barcode_transaktionen.html')

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
