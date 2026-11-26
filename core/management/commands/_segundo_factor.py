"""Muestra en la terminal lo que la persona necesita para su segundo factor.

Va a stdout y nunca a los logs. Se muestra una sola vez: no se puede volver a pedir.
"""
from base64 import b32encode


def mostrar_segundo_factor(salida, totp, codigos):
    salida.write("")
    salida.write("Agrega la cuenta en la app del autenticador con este enlace:")
    salida.write(f"  {totp.config_url}")
    salida.write("O escribe la clave a mano:")
    salida.write(f"  {b32encode(totp.bin_key).decode()}")
    salida.write("")
    salida.write("Códigos de recuperación, de un solo uso. Guárdalos fuera del celular:")
    for codigo in codigos:
        salida.write(f"  {codigo}")
    salida.write("")
    salida.write("Esta información no se vuelve a mostrar.")
