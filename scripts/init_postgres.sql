-- Rol de la aplicación sin superusuario, igual que en Neon (mínimo privilegio).
-- Lo usan docker-compose (al crear el volumen) y el job "calidad" del CI.
-- Credenciales solo para desarrollo local y CI: nunca se usan en Render.
-- CREATEDB solo para que pytest-django pueda crear la base de pruebas.
CREATE ROLE alerta LOGIN NOSUPERUSER NOCREATEROLE CREATEDB PASSWORD 'alerta';
CREATE DATABASE alerta OWNER alerta;
