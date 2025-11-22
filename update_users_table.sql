-- SQL commands to update the 'users' table for Google OAuth integration

ALTER TABLE users
ADD COLUMN email VARCHAR(255) UNIQUE NOT NULL AFTER username,
ADD COLUMN google_id VARCHAR(255) UNIQUE DEFAULT NULL AFTER password_hash,
MODIFY COLUMN password_hash VARCHAR(255) DEFAULT NULL;
