function [dSOC] = ECMSOC(tt,c, I, It)
% This is the function containing the ODEs for the chosen equivalent
% circuit model. 

% Nomenclature:

% I     - Input - The requires charge/discharge of the cell
% c     - Input - Vector containing the inital SOC and Voltage. 
% It    - Input - This is the time frame of I, needed due to I also being a
%                 function of t
% tt    - Input - The time span that the ODE is solved for
% dSOC - Output - This is a matrix contain all solved outputs. Column 1 is
%                 the SOC, column 2 is the voltage over C_p1 and column 3 
%                 is the voltage over C_p2. 

% Global allows the function to use the values assigned to these parameters
% in the "NMC.m" file. These have also been explained there. 

global R_p1 C_p1 R_p2 C_p2 Q_n w1 w2 w3

I_actual = interp1(It, I, tt); % As I changes with time it is rtequired to 
                               % interpolate so the ode can estimate the I
                               % at the time steps it uses

U1 = c(2); U2 = c(3); % This takes the values out of the matrix. 

% These are the ODEs used. 
dSOC(1) = -(1/Q_n)*I_actual + w1;
dSOC(2) = -(1/(R_p1*C_p1))*U1 + (1/C_p1)*I_actual + w2;
dSOC(3) = -(1/(R_p2*C_p2))*U2 + (1/C_p2)*I_actual + w3;


dSOC = dSOC';% Finally, it is required that the output be a column vector so we have to transpose the output
end