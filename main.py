import cv2
import mediapipe as mp
import numpy as np
import random
import time
import pygame
from collections import deque

# --------- Config ---------
COUNTDOWN_SECS  = 2.5   # duração do countdown
SMOOTH_WINDOW   = 8     # janela para exibir leitura “suavizada” (apenas visual)
READY_FRAMES    = 6     # frames estáveis para travar a jogada
RELEASE_FRAMES  = 6     # frames sem jogada válida para liberar nova rodada
SHOW_RESULT_SECS= 2.0   # quanto tempo mostrar o resultado
FRAME_W, FRAME_H = 800, 600 # resolução do vídeo
CAM_INDEX = 0 # Índice da câmera
# --------------------------

mp_hands = mp.solutions.hands # módulo de mãos do MediaPipe
mp_draw = mp.solutions.drawing_utils # utilitários de desenho
mp_styles = mp.solutions.drawing_styles # estilos de desenho

pygame.mixer.init()
sound_win = pygame.mixer.Sound("./sounds/win.mp3")
sound_lose = pygame.mixer.Sound("./sounds/lose.mp3")
sound_draw = pygame.mixer.Sound("./sounds/draw.mp3")

CHOICES = ["PEDRA", "PAPEL", "TESOURA"]

WIN_MAP = {
    ("PEDRA", "TESOURA"): "Voce ganhou",
    ("TESOURA", "PAPEL"): "Voce ganhou",
    ("PAPEL", "PEDRA"): "Voce ganhou",
}

# Verifica o resultado do jogo
def judge(player, bot):
    if player == bot: return "Empate"
    return WIN_MAP.get((player, bot), "Bot ganhou")

# Retorna o estado (estendido ou dobrado) de cada dedo
def finger_states(hand_landmarks, hand_label):
    if not hand_landmarks:
        return None

    # Extração de pontos de referência da mão
    landmarks = hand_landmarks.landmark

    right = (hand_label == "Right")

    # Estados dos dedos (verdadeiro = estendido, falso = dobrado)
    thumb_up = landmarks[4].x < landmarks[3].x if right else landmarks[4].x > landmarks[3].x
    index_up = landmarks[8].y < landmarks[6].y
    middle_up = landmarks[12].y < landmarks[10].y
    ring_up = landmarks[16].y < landmarks[14].y
    pinky_up = landmarks[20].y < landmarks[18].y
    
    return [thumb_up, index_up, middle_up, ring_up, pinky_up]

# Classifica a jogada com base nos estados dos dedos
def classify_rps(fingers_up):
    thumb, i, m, r, p = fingers_up
    total_up = sum(fingers_up)
    
    if total_up <= 1:
        return "PEDRA"
    elif total_up >= 4:
        return "PAPEL"
    elif i and m and not r and not p:
        return "TESOURA"
    else:
        return "INDEFINIDO"   


def start_rps_game():
    cap = cv2.VideoCapture(CAM_INDEX)
    if not cap.isOpened():  
        print("Erro ao abrir a camera.")
        return None
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    
    recent_predictions = deque(maxlen=SMOOTH_WINDOW)  # Votação por moda
    
    # placar
    score_you = 0
    score_bot = 0

    # máquina de estados
    state = "IDLE"              # IDLE -> COUNTDOWN -> SHOW
    ready_choice_prev = None    # última jogada “candidata”
    ready_count = 0             # quantos frames seguidos iguais
    locked_choice = None        # jogada travada para a rodada
    bot_choice = None
    countdown_end = 0.0
    show_end = 0.0
    release_count = 0           # frames seguidos SEM jogada para liberar nova

    last_result_text = ""

    
    with mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.6
    ) as hands:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.flip(frame, 1) # espelha a imagem
            h, w = frame.shape[:2] # altura e largura do frame

            # --- detecção e classificação do frame atual ---
            current_choice = None
            states_txt = ""

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) # converte para RGB
            results = hands.process(frame_rgb) # processa a imagem

            
            if results.multi_hand_landmarks and results.multi_handedness:
                hlms = results.multi_hand_landmarks[0]
                label = results.multi_handedness[0].classification[0].label

                # desenha os pontos de referência
                mp_draw.draw_landmarks(
                    frame, hlms, mp_hands.HAND_CONNECTIONS,
                    mp_styles.get_default_hand_landmarks_style(),
                    mp_styles.get_default_hand_connections_style()
                )

                states = finger_states(hlms, label)
                pred = classify_rps(states)
                recent_predictions.append(pred) # adiciona para votação

                if pred in CHOICES:
                    current_choice = pred

                states_txt = " ".join("1" if s else "0" for s in states)

            ui_choice = "—"
            if len(recent_predictions):
                vals, counts = np.unique(np.array(recent_predictions), return_counts=True)
                ui_choice = vals[np.argmax(counts)]

            now = time.time()

            # ----------------- STATE MACHINE -----------------
            if state == "IDLE":
                # precisa manter a MESMA jogada por READY_FRAMES frames para travar
                if current_choice is not None:
                    if current_choice == ready_choice_prev:
                        ready_count += 1
                    else:
                        ready_choice_prev = current_choice
                        ready_count = 1

                    if ready_count >= READY_FRAMES:
                        locked_choice = current_choice
                        bot_choice = random.choice(CHOICES)
                        countdown_end = now + COUNTDOWN_SECS
                        state = "COUNTDOWN"
                        # prepara para próxima liberação
                        release_count = 0
                else:
                    ready_choice_prev = None
                    ready_count = 0

            elif state == "COUNTDOWN":
                remaining = countdown_end - now
                if remaining > 0:
                    txt = f"Mostre o gesto! {remaining:0.1f}s"
                    cv2.putText(frame, txt, (10, 55),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 4)
                    cv2.putText(frame, txt, (10, 55),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
                else:
                    # JULGA usando a jogada TRAVADA (evita “indefinido” de última hora)
                    verdict = judge(locked_choice, bot_choice)
                    last_result_text = f"Voce: {locked_choice} | Bot: {bot_choice}  →  {verdict}"

                    # cor do resultado
                    if verdict == "Voce ganhou":
                        score_you += 1
                        result_color = (0, 255, 0)      # verde
                        sound_win.play()
                    elif verdict == "Bot ganhou":
                        score_bot += 1
                        result_color = (0, 0, 255)      # vermelho
                        sound_lose.play()
                    else:
                        result_color = (0, 255, 255)    # amarelo (empate)
                        sound_draw.play()

                    show_end = now + SHOW_RESULT_SECS
                    state = "SHOW"

            elif state == "SHOW":
                # conta quantos frames estamos “liberados” (sem jogada válida)
                if current_choice is None:
                    release_count += 1
                else:
                    release_count = 0

                if now >= show_end and release_count >= RELEASE_FRAMES:
                    # reseta para nova rodada
                    state = "IDLE"
                    locked_choice = None
                    bot_choice = None
                    ready_choice_prev = None
                    ready_count = 0
                    last_result_text = ""

            # ----------------- HUD / UI -----------------
            cv2.rectangle(frame, (0, 0), (w, 90), (25, 25, 25), -1)
            cv2.putText(frame, f"Leitura: {ui_choice}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.putText(frame, f"Travada: {locked_choice if locked_choice else '—'}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 255, 200), 2)
            cv2.putText(frame, f"Bot: {bot_choice if bot_choice else '—'}", (w - 200, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 220, 255), 2)
            cv2.putText(frame, f"Placar  Voce {score_you} x {score_bot} Bot", (w - 420, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 240, 200), 2)

            # mostra o resultado no rodapé    
            if last_result_text and state in ("COUNTDOWN", "SHOW"):
                # mostra resultado se0 existir
                (tw, th), _ = cv2.getTextSize(last_result_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                cv2.rectangle(frame, (10, h - 40 - th), (10 + tw + 20, h - 18), (0, 0, 0), -1)
                cv2.putText(frame, last_result_text, (18, h - 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, result_color, 2)
            
            # mostra os estados dos dedos
            if states_txt:
                cv2.putText(frame, states_txt, (10, 110),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 255, 180), 2)

            cv2.putText(frame, f"Estado: {state}   (Q: sair | R: reset placar)", (10, h - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1)

            # Exibir o vídeo
            cv2.imshow('Rock Paper Scissors', frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            if key == ord('r'):
                score_you = score_bot = 0


    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    start_rps_game()